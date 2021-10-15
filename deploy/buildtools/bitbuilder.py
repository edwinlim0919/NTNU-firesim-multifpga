""" This converts the build configuration files into something usable by the
manager """

from __future__ import with_statement
from time import strftime, gmtime
import ConfigParser
import pprint
import sys
import json
import time
import random
import string
import logging

from fabric.api import *
from fabric.contrib.console import confirm
from fabric.contrib.project import rsync_project
from awstools.afitools import *
from awstools.awstools import *
from buildtools.build import get_deploy_dir
from util.streamlogger import StreamLogger, InfoStreamLogger

rootLogger = logging.getLogger()

def get_deploy_dir():
    """ Must use local here. determine where the firesim/deploy dir is """
    with StreamLogger('stdout'), StreamLogger('stderr'):
        deploydir = local("pwd", capture=True)
    return deploydir

class BitBuilder:
    def __init__(self, build_config):
        self.build_config = build_config
        return

    def get_remote_build_dir(self):
        if not self.build_config.build_farm_dispatcher.is_local:
            # remote paths
            remote_home_dir = ""
            with StreamLogger('stdout'), StreamLogger('stderr'):
                remote_home_dir = run('echo $HOME')

            # potentially override build dir
            if self.build_config.build_farm_dispatcher.override_remote_build_dir:
                remote_home_dir = self.build_config.build_farm_dispatcher.override_remote_build_dir

            return remote_home_dir
        else:
            return None

    def replace_rtl(self):
        return

    def build_driver(self):
        return

    def build_bitstream(self, bypass=False):
        return

class F1BitBuilder(BitBuilder):
    def replace_rtl(self):
        """ Generate Verilog """
        rootLogger.info("Building AWS F1 Verilog for {}".format(self.build_config.get_chisel_triplet()))
        with InfoStreamLogger('stdout'), InfoStreamLogger('stderr'):
            run("{}/general-scripts/replace-rtl.sh {} {} {} {} \"{}\"".format(
                get_deploy_dir() + "/buildtools",
                os.getenv('RISCV', ""),
                os.getenv('PATH', ""),
                os.getenv('LD_LIBRARY_PATH', ""),
                get_deploy_dir() + "/..",
                self.build_config.make_recipe("PLATFORM=f1 replace-rtl")))

    def build_driver(self):
        """ Build FPGA driver """
        rootLogger.info("Building AWS F1 FPGA driver for {}".format(self.build_config.get_chisel_triplet()))
        with InfoStreamLogger('stdout'), InfoStreamLogger('stderr'):
            run("{}/general-scripts/build-driver.sh {} {} {} {} \"{}\"".format(
                get_deploy_dir() + "/buildtools",
                os.getenv('RISCV', ""),
                os.getenv('PATH', ""),
                os.getenv('LD_LIBRARY_PATH', ""),
                get_deploy_dir() + "/..",
                self.build_config.make_recipe("PLATFORM=f1 driver")))


    def remote_setup(self):
        fpga_build_postfix = "hdk/cl/developer_designs/cl_{}".format(self.build_config.get_chisel_triplet())

        # local paths
        local_awsfpga_dir = "{}/../platforms/f1/aws-fpga".format(get_deploy_dir())

        # remote paths
        remote_home_dir = get_remote_build_dir()
        remote_build_dir = "{}/firesim-build".format(remote_home_dir)
        remote_f1_platform_dir = "{}/platforms/f1/".format(remote_build_dir)
        remote_awsfpga_dir = "{}/aws-fpga".format(remote_f1_platform_dir)

        # copy aws-fpga to the build instance.
        # do the rsync, but ignore any checkpoints that might exist on this machine
        # (in case builds were run locally)
        # extra_opts -l preserves symlinks
        with StreamLogger('stdout'), StreamLogger('stderr'):
            run('mkdir -p {}'.format(remote_f1_platform_dir))
            rsync_cap = rsync_project(
                local_dir=local_awsfpga_dir,
                remote_dir=remote_f1_platform_dir,
                ssh_opts="-o StrictHostKeyChecking=no",
                exclude="hdk/cl/developer_designs/cl_*",
                extra_opts="-l", capture=True)
            rootLogger.debug(rsync_cap)
            rootLogger.debug(rsync_cap.stderr)
            rsync_cap = rsync_project(
                local_dir="{}/{}/*".format(local_awsfpga_dir, fpga_build_postfix),
                remote_dir='{}/{}'.format(remote_awsfpga_dir, fpga_build_postfix),
                exclude='build/checkpoints',
                ssh_opts="-o StrictHostKeyChecking=no",
                extra_opts="-l", capture=True)
            rootLogger.debug(rsync_cap)
            rootLogger.debug(rsync_cap.stderr)

        return "{}/{}".format(remote_awsfpga_dir, fpga_build_postfix)

    def build_bitstream(self, bypass=False):
        """ Run Vivado, convert tar -> AGFI/AFI. Then terminate the instance at the end.
        bypass: since this function takes a long time, bypass just returns for
        testing purposes when set to True. """

        if bypass:
            self.build_config.build_farm_dispatcher.terminate_build_instance()
            return

        # The default error-handling procedure. Send an email and teardown instance
        def on_build_failure():
            message_title = "FireSim FPGA Build Failed"

            message_body = "Your FPGA build failed for triplet: " + self.build_config.get_chisel_triplet()

            send_firesim_notification(message_title, message_body)

            rootLogger.info(message_title)
            rootLogger.info(message_body)

            self.build_config.build_farm_dispatcher.terminate_build_instance()

        rootLogger.info("Building AWS F1 AGFI from Verilog")

        local_deploy_dir = get_deploy_dir()
        fpga_build_postfix = "hdk/cl/developer_designs/cl_{}".format(self.build_config.get_chisel_triplet())
        local_results_dir = "{}/results-build/{}".format(local_deploy_dir, self.build_config.get_build_dir_name())

        # cl_dir is the cl_dir that is either local or remote
        # if locally no need to copy things around (the makefile should have already created a CL_DIR w. the tuple)
        # if remote (aka not locally) then you need to copy things
        cl_dir = ""

        if self.build_config.build_farm_dispatcher.is_local:
            cl_dir = "{}/../platforms/f1/aws-fpga/{}".format(local_deploy_dir, fpga_build_postfix)
        else:
            cl_dir = remote_setup()

        vivado_result = 0
        with InfoStreamLogger('stdout'), InfoStreamLogger('stderr'):
            # copy script to the cl_dir and execute
            rsync_cap = rsync_project(
                local_dir="{}/buildtools/platform-specific-scripts/f1/build-bitstream.sh".format(local_deploy_dir),
                remote_dir="{}/".format(cl_dir),
                ssh_opts="-o StrictHostKeyChecking=no",
                extra_opts="-l", capture=True)
            rootLogger.debug(rsync_cap)
            rootLogger.debug(rsync_cap.stderr)

            vivado_result = run("{}/build-bitstream.sh {}".format(cl_dir, cl_dir)).return_code

        # put build results in the result-build area
        with StreamLogger('stdout'), StreamLogger('stderr'):
            rsync_cap = rsync_project(
                local_dir="{}/".format(local_results_dir),
                remote_dir="{}".format(cl_dir),
                ssh_opts="-o StrictHostKeyChecking=no", upload=False, extra_opts="-l",
                capture=True)
            rootLogger.debug(rsync_cap)
            rootLogger.debug(rsync_cap.stderr)

        if vivado_result != 0:
            on_build_failure()
            return

        if not aws_create_afi():
            on_build_failure()
            return

        self.build_config.build_farm_dispatcher.terminate_build_instance()

    def aws_create_afi(self):
        """
        Convert the tarball created by Vivado build into an Amazon Global FPGA Image (AGFI)

        :return: None on error
        """

        local_deploy_dir = get_deploy_dir()
        local_results_dir = "{}/results-build/{}".format(local_deploy_dir, self.build_config.get_build_dir_name())

        afi = None
        agfi = None
        s3bucket = self.build_config.s3_bucketname
        afiname = self.build_config.name

        # construct the "tags" we store in the AGFI description
        tag_buildtriplet = self.build_config.get_chisel_triplet()
        tag_deploytriplet = tag_buildtriplet
        if self.build_config.deploytriplet != "None":
            tag_deploytriplet = self.build_config.deploytriplet

        # the asserts are left over from when we tried to do this with tags
        # - technically I don't know how long these descriptions are allowed to be,
        # but it's at least 256*3, so I'll leave these here for now as sanity
        # checks.
        assert len(tag_buildtriplet) <= 255, "ERR: aws does not support tags longer than 256 chars for buildtriplet"
        assert len(tag_deploytriplet) <= 255, "ERR: aws does not support tags longer than 256 chars for deploytriplet"

        with StreamLogger('stdout'), StreamLogger('stderr'):
            is_dirty_str = local("if [[ $(git status --porcelain) ]]; then echo '-dirty'; fi", capture=True)
            hash = local("git rev-parse HEAD", capture=True)
        tag_fsimcommit = hash + is_dirty_str

        assert len(tag_fsimcommit) <= 255, "ERR: aws does not support tags longer than 256 chars for fsimcommit"

        # construct the serialized description from these tags.
        description = firesim_tags_to_description(tag_buildtriplet, tag_deploytriplet, tag_fsimcommit)

        # if we're unlucky, multiple vivado builds may launch at the same time. so we
        # append the build node IP + a random string to diff them in s3
        global_append = "-" + str(env.host_string) + "-" + ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(10)) + ".tar"

        with lcd("""{}/cl_{}/build/checkpoints/to_aws/""".format(local_results_dir, tag_buildtriplet)), StreamLogger('stdout'), StreamLogger('stderr'):
            files = local('ls *.tar', capture=True)
            rootLogger.debug(files)
            rootLogger.debug(files.stderr)
            tarfile = files.split()[-1]
            s3_tarfile = tarfile + global_append
            localcap = local('aws s3 cp ' + tarfile + ' s3://' + s3bucket + '/dcp/' + s3_tarfile, capture=True)
            rootLogger.debug(localcap)
            rootLogger.debug(localcap.stderr)
            agfi_afi_ids = local("""aws ec2 create-fpga-image --input-storage-location Bucket={},Key={} --logs-storage-location Bucket={},Key={} --name "{}" --description "{}" """.format(s3bucket, "dcp/" + s3_tarfile, s3bucket, "logs/", afiname, description), capture=True)
            rootLogger.debug(agfi_afi_ids)
            rootLogger.debug(agfi_afi_ids.stderr)
            rootLogger.debug("create-fpge-image result: " + str(agfi_afi_ids))
            ids_as_dict = json.loads(agfi_afi_ids)
            agfi = ids_as_dict["FpgaImageGlobalId"]
            afi = ids_as_dict["FpgaImageId"]
            rootLogger.info("Resulting AGFI: " + str(agfi))
            rootLogger.info("Resulting AFI: " + str(afi))

        rootLogger.info("Waiting for create-fpga-image completion.")
        results_build_dir = """{}/""".format(local_results_dir)
        checkstate = "pending"
        with lcd(results_build_dir), StreamLogger('stdout'), StreamLogger('stderr'):
            while checkstate == "pending":
                imagestate = local("""aws ec2 describe-fpga-images --fpga-image-id {} | tee AGFI_INFO""".format(afi), capture=True)
                state_as_dict = json.loads(imagestate)
                checkstate = state_as_dict["FpgaImages"][0]["State"]["Code"]
                rootLogger.info("Current state: " + str(checkstate))
                time.sleep(10)


        if checkstate == "available":
            # copy the image to all regions for the current user
            copy_afi_to_all_regions(afi)

            message_title = "FireSim FPGA Build Completed"
            agfi_entry = "[" + afiname + "]\n"
            agfi_entry += "afgi=" + agfi + "\n"
            agfi_entry += "deploytripletoverride=None\n"
            agfi_entry += "customruntimeconfig=None\n"
            message_body = "Your AGFI has been created!\nAdd\n\n" + agfi_entry + "\nto your config_hwdb.ini to use this hardware configuration."

            send_firesim_notification(message_title, message_body)

            rootLogger.info(message_title)
            rootLogger.info(message_body)

            # for convenience when generating a bunch of images. you can just
            # cat all the files in this directory after your builds finish to get
            # all the entries to copy into config_hwdb.ini
            hwdb_entry_file_location = """{}/built-hwdb-entries/""".format(local_deploy_dir)
            local("mkdir -p " + hwdb_entry_file_location)
            with open(hwdb_entry_file_location + "/" + afiname, "w") as outputfile:
                outputfile.write(agfi_entry)

            if self.build_config.post_build_hook:
                with StreamLogger('stdout'), StreamLogger('stderr'):
                    localcap = local("""{} {}""".format(self.build_config.post_build_hook,
                                                        results_build_dir,
                                                        capture=True))
                    rootLogger.debug("[localhost] " + str(localcap))
                    rootLogger.debug("[localhost] " + str(localcap.stderr))

            rootLogger.info("Build complete! AFI ready. See {}.".format(os.path.join(hwdb_entry_file_location,afiname)))
            return True
        else:
            return
