# Read-only telemetry. It never changes a candidate, native query, or gate.
namespace eval jip {
    variable active 0;variable out {};variable started 0;variable last 0
    variable current_phase {};variable phase_started 0;variable stream {}
    variable completed 0;variable total 0
}
proc jip::begin {folder} {
    variable active;variable out;variable started;variable last;variable stream
    variable current_phase;variable phase_started;variable completed;variable total
    if {$active} {error "Nested joint-input progress scope"}
    set out $folder;set active 1;set started [clock microseconds];set last $started
    set current_phase {};set phase_started $started;set completed 0;set total 0
    set stream [open $out/ji_candidate_runtime.tsv w]
    puts $stream "id\telapsed_us\tcone_cells\tstatus";flush $stream
    set f [open $out/ji_phase_runtime.tsv w];puts $f "phase\telapsed_us";close $f
    phase snapshot_load
}
proc jip::checkpoint {{force 0}} {
    variable active;variable last;variable out;variable started
    variable current_phase;variable completed;variable total
    if {!$active} {return}
    set now [clock microseconds]
    if {!$force && $now-$last<30000000} {return}
    set last $now
    set f [open $out/ji_progress.tsv.tmp w];puts $f "key\tvalue"
    foreach {key value} [list epoch [clock seconds] phase $current_phase completed_candidates $completed total_candidates $total elapsed_us [expr {$now-$started}]] {puts $f "$key\t$value"}
    close $f;file rename -force $out/ji_progress.tsv.tmp $out/ji_progress.tsv
    locality_inventory::connection_save $out/locality/candidate_input_reuse.live.tsv
    puts "JOINT_INPUT [clock seconds] phase=$current_phase candidates=$completed/$total elapsed_ms=[expr {($now-$started)/1000}]";flush stdout
}
proc jip::phase {name} {
    variable active;variable out;variable current_phase;variable phase_started
    if {!$active} {return}
    set now [clock microseconds]
    if {$current_phase ne ""} {
        set f [open $out/ji_phase_runtime.tsv a]
        puts $f "$current_phase\t[expr {$now-$phase_started}]";close $f
    }
    set current_phase $name;set phase_started $now;checkpoint 1
}
proc jip::candidate {id tick cone_size status} {
    variable active;variable stream;variable completed
    if {!$active} {return}
    incr completed
    set status [string map [list \t { } \r { } \n { }] $status]
    puts $stream [join [list $id [expr {[clock microseconds]-$tick}] $cone_size $status] \t];flush $stream
    checkpoint [expr {$completed==1 || $completed%16==0}]
}
proc jip::end {status} {
    variable active;variable stream
    if {!$active} {return}
    phase $status;close $stream;set stream {};set active 0
}
