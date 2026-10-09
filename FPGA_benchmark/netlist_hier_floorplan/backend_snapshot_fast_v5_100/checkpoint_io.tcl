# Isolate checkpoint serialization from the normal implementation thread limit.
# This is a guarded workaround trial, not a claimed fix for all native failures.
if {![llength [info commands ::checkpointio_native_write]]} {
    rename ::write_checkpoint ::checkpointio_native_write
    proc ::write_checkpoint {args} {
        set previous [get_param general.maxThreads]
        set_param general.maxThreads 1
        puts "CHECKPOINT_IO begin threads=1 previous=$previous args=$args"
        flush stdout
        set code [catch {uplevel 1 [linsert $args 0 ::checkpointio_native_write]} result options]
        set restore_code [catch {set_param general.maxThreads $previous} restore_result restore_options]
        puts "CHECKPOINT_IO end returncode=$code restore_returncode=$restore_code threads=[get_param general.maxThreads]"
        flush stdout
        if {$restore_code} {return -options $restore_options $restore_result}
        return -options $options $result
    }
}
