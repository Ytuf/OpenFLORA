# Device-geometry probe: the recipe for adding a new part.
#
# Run in Vivado (tested with 2019.1) with the target part substituted below;
# it needs no design, only the device database:
#
#   vivado -mode batch -source probe_geometry.tcl
#
# then feed the output to tools/build_device_model.py to produce the
# device-model JSON. Dumps:
#  1. per-clock-region site counts + X/Y ranges (SLICE / RAMB36 / RAMB18 / DSP48)
#  2. per-column Y extents for each site family
#  3. the ENTIRE tile grid (COLUMN ROW TILE_TYPE NAME) so the model builder
#     can reconstruct fabric columns + interconnect pairing without any
#     guessed layout
#  4. site->tile mapping for column heads
create_project -in_memory -part xc7z020clg400-1
link_design -part xc7z020clg400-1

set fp [open "probe_geometry_out.txt" w]

puts $fp "=== per-clock-region site counts (name-pattern matched) ==="
foreach cr [get_clock_regions] {
  foreach pat {SLICE RAMB36 RAMB18 DSP48} {
    set sites [get_sites -of_objects [get_clock_regions $cr] -filter "NAME =~ ${pat}_X*" -quiet]
    set n [llength $sites]
    if {$n == 0} { puts $fp "CR $cr $pat count=0"; continue }
    set xs {}; set ys {}
    foreach s $sites {
      set nm "$s"
      set base [string range $nm [expr {[string last "_X" $nm] + 2}] end]
      lappend xs [lindex [split $base Y] 0]
      lappend ys [lindex [split $base Y] 1]
    }
    set xs [lsort -integer $xs]; set ys [lsort -integer $ys]
    puts $fp "CR $cr $pat count=$n X=[lindex $xs 0]..[lindex $xs end] Y=[lindex $ys 0]..[lindex $ys end]"
  }
}

puts $fp "=== per-column Y extents ==="
foreach pat {SLICE RAMB36 RAMB18 DSP48} {
  set seen {}
  foreach s [get_sites ${pat}_X*Y*] {
    set nm "$s"
    set base [string range $nm [expr {[string last "_X" $nm] + 2}] end]
    set xv [lindex [split $base Y] 0]
    if {[lsearch -exact $seen $xv] < 0} { lappend seen $xv }
  }
  foreach xv [lsort -integer $seen] {
    set ys {}
    foreach s [get_sites ${pat}_X${xv}Y*] {
      set nm "$s"
      set base [string range $nm [expr {[string last "_X" $nm] + 2}] end]
      lappend ys [lindex [split $base Y] 1]
    }
    set ys [lsort -integer $ys]
    puts $fp "COL ${pat}_X$xv n=[llength $ys] Y=[lindex $ys 0]..[lindex $ys end]"
  }
}

puts $fp "=== full tile grid: COLUMN ROW TYPE NAME ==="
foreach t [get_tiles] {
  set ty [get_property TILE_TYPE $t]
  if {$ty eq "NULL"} { continue }
  puts $fp "TILE [get_property COLUMN $t] [get_property ROW $t] $ty $t"
}

puts $fp "=== site->tile maps (column heads) ==="
foreach s [get_sites SLICE_X*Y0]  { puts $fp "MAP $s [get_tiles -of_objects $s]" }
foreach s [get_sites SLICE_X*Y149] { puts $fp "MAPTOP $s [get_tiles -of_objects $s]" }
foreach s [get_sites RAMB36_X*Y*] { puts $fp "MAPB $s [get_tiles -of_objects $s]" }
foreach s [get_sites DSP48_X*Y*]  { puts $fp "MAPD $s [get_tiles -of_objects $s]" }
foreach s [get_sites RAMB18_X*Y*] { puts $fp "MAPB18 $s [get_tiles -of_objects $s]" }

puts $fp "=== device totals ==="
foreach pat {SLICE RAMB36 RAMB18 DSP48} {
  puts $fp "TOTAL $pat [llength [get_sites ${pat}_X*Y*]]"
}
close $fp
exit
