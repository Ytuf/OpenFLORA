# Device-geometry probe: the recipe for adding a new part.
#
# Run in Vivado (tested with 2019.1), naming the part (default xc7z020clg400-1);
# it needs no design, only the device database:
#
#   vivado -mode batch -source probe_geometry.tcl -tclargs xc7z020clg400-1
#
# then feed the output to tools/build_device_model.py to produce the
# device-model JSON. Dumps:
#  1. per-clock-region site counts + X/Y ranges (SLICE / RAMB36 / RAMB18 / DSP48)
#  2. per-column Y extents for each site family
#  3. the ENTIRE tile grid (COLUMN ROW TILE_TYPE NAME) so the model builder
#     can reconstruct fabric columns + interconnect pairing without any
#     guessed layout
#  4. site->tile mapping for column heads
#  5. the interconnect inventory of sample INT tiles (routing wires per
#     tile, their spans): the partition-pin routability model's device facts
#  6. per-column, per-clock-region-row site counts (parts whose columns are
#     not full height everywhere)
set part xc7z020clg400-1
if {[llength $argv] > 0} { set part [lindex $argv 0] }
create_project -in_memory -part $part
link_design -part $part

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

# 5. interconnect inventory, for the partition-pin routability model: every
#    node NAMED in a sample interconnect tile (one per fabric column, the
#    middle row of each clock region), its cost class, and how many
#    interconnect columns (dx) and rows (dy) it spans -- measured from the
#    INT_L/INT_R tiles the node touches (INT_TILE_X/Y), not from wire names.
#    INTW <tile> <wire> <cost class> <dx> <dy>
puts $fp "=== interconnect inventory ==="
foreach cr [get_clock_regions] {
  set ys {}
  foreach t [get_tiles -quiet -of_objects [get_clock_regions $cr] -filter {TYPE == INT_L || TYPE == INT_R}] {
    lappend ys [get_property INT_TILE_Y $t]
  }
  if {[llength $ys] == 0} { continue }
  set ys [lsort -integer -unique $ys]
  set ymid [lindex $ys [expr {[llength $ys] / 2}]]
  foreach t [get_tiles -quiet -of_objects [get_clock_regions $cr] -filter "(TYPE == INT_L || TYPE == INT_R) && INT_TILE_Y == $ymid"] {
    foreach n [get_nodes -quiet -of_objects $t] {
      set nm [get_property NAME $n]
      if {[string first "$t/" $nm] != 0} { continue }
      set xs {}; set yv {}
      foreach tt [get_tiles -quiet -of_objects $n -filter {TYPE == INT_L || TYPE == INT_R}] {
        lappend xs [get_property INT_TILE_X $tt]; lappend yv [get_property INT_TILE_Y $tt]
      }
      if {[llength $xs] == 0} { continue }
      set xs [lsort -integer $xs]; set yv [lsort -integer $yv]
      puts $fp "INTW $t [lindex [split $nm /] 1] [get_property COST_CODE_NAME $n] [expr {[lindex $xs end] - [lindex $xs 0]}] [expr {[lindex $yv end] - [lindex $yv 0]}]"
    }
  }
}

# 6. per-column, per-clock-region-row site counts and the lowest site of each
#    column, so that parts whose columns are not full height everywhere
#    (occluded by a processor subsystem, GTs, configuration blocks) are read
#    cell by cell.  COLROW <family> <site X> <row> <count>; MAPLO <site> <tile>
puts $fp "=== per-column clock-region-row site counts ==="
foreach {pat perrow} {SLICE 50 RAMB36 10 DSP48 20} {
  set cnt [dict create]
  set lo [dict create]
  foreach s [get_sites ${pat}_X*Y*] {
    set nm "$s"
    set base [string range $nm [expr {[string last "_X" $nm] + 2}] end]
    set xv [lindex [split $base Y] 0]
    set yv [lindex [split $base Y] 1]
    dict incr cnt "$xv [expr {$yv / $perrow}]"
    if {![dict exists $lo $xv] || $yv < [lindex [dict get $lo $xv] 0]} {
      dict set lo $xv [list $yv $nm]
    }
  }
  foreach k [lsort [dict keys $cnt]] { puts $fp "COLROW $pat $k [dict get $cnt $k]" }
  foreach xv [lsort -integer [dict keys $lo]] {
    set nm [lindex [dict get $lo $xv] 1]
    puts $fp "MAPLO $nm [get_tiles -of_objects [get_sites $nm]]"
  }
}
close $fp
exit
