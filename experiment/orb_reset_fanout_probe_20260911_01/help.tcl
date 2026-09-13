foreach command {insert_buffer create_cell connect_net disconnect_net} {
    puts "COMMAND_HELP=$command"
    help $command
}
