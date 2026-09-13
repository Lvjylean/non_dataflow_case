foreach command {create_cell connect_net disconnect_net create_net} {
    puts "COMMAND_HELP=$command"
    catch {help $command} message
    puts $message
}
