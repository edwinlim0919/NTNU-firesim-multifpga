set root_dir [pwd]
set vivado_version [version -short]

proc retrieveVersionedFile {filename version} {
  set first [file rootname $filename]
  set last [file extension $filename]
  if {[file exists ${first}_${version}${last}]} {
    return ${first}_${version}${last}
  }
  return $filename
}

if {![file exists [set sourceFile [retrieveVersionedFile ${root_dir}/scripts/platform_env.tcl $vivado_version]]]} {
    puts "ERROR: could not find $sourceFile"
    exit 1
}
source $sourceFile

# Cleanup
foreach path [list ${root_dir}/vivado_proj/firesim.bit] {
    if {[file exists ${path}]} {
        file delete -force -- ${path}
    }
}

create_project -force firesim ${root_dir}/vivado_proj -part $part
set_property board_part $board_part [current_project]

# Loading all the verilog files
foreach addFile [list ${root_dir}/design/axi_tieoff_master.v ${root_dir}/design/firesim_wrapper.v ${root_dir}/design/firesim_top.sv ${root_dir}/design/firesim_defines.vh] {
  set addFile [retrieveVersionedFile $addFile $vivado_version]
  if {![file exists $addFile]} {
    puts "ERROR: could not find file $addFile"
    exit 1
  }
  add_files $addFile
  if {[file extension $addFile] == ".vh"} {
    set_property IS_GLOBAL_INCLUDE 1 [get_files $addFile]
  }
}

# Loading firesim_env.tcl
if {[file exists [set sourceFile [retrieveVersionedFile ${root_dir}/scripts/firesim_env.tcl $vivado_version]]]} {
  source $sourceFile
}

# Loading create_bd.tcl
if {![file exists [set sourceFile [retrieveVersionedFile ${root_dir}/scripts/create_bd.tcl $vivado_version]]]} {
  puts "ERROR: could not find $sourceFile"
  exit 1
}
source $sourceFile

# Making wrapper
make_wrapper -files [get_files ${root_dir}/vivado_proj/firesim.srcs/sources_1/bd/design_1/design_1.bd] -top
add_files -norecurse ${root_dir}/vivado_proj/firesim.gen/sources_1/bd/design_1/hdl/design_1_wrapper.v

# Adding additional constraint sets

if {[file exists [set constrFile [retrieveVersionedFile ${root_dir}/design/firesim_synth.xdc $vivado_version]]]} {
    create_fileset -constrset synth
    add_files -fileset synth -norecurse $constrFile
}

if {[file exists [set constrFile [retrieveVersionedFile ${root_dir}/design/firesim_impl.xdc $vivado_version]]]} {
    create_fileset -constrset impl
    add_files -fileset impl -norecurse $constrFile
}

update_compile_order -fileset sources_1
set_property top design_1_wrapper [current_fileset]
update_compile_order -fileset sources_1

if {[llength [get_filesets -quiet synth]]} {
    set_property constrset synth [get_runs synth_1]
}

if {[llength [get_filesets -quiet impl]]} {
    set_property constrset impl [get_runs impl_1]
}

foreach sourceFile [list ${root_dir}/scripts/synthesis.tcl ${root_dir}/scripts/implementation.tcl] {
  set sourceFile [retrieveVersionedFile ${root_dir}/scripts/synthesis.tcl $vivado_version]
  if {![file exists $sourceFile]} {
    puts "ERROR: could not find $sourceFile"
    exit 1
  }
  source $sourceFile
}

puts "Done!"
exit 0
