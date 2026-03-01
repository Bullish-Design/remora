set runtimepath+=/home/andrew/Documents/Projects/remora
lua require('remora_nvim').setup({ socket = '/run/user/1000/remora.sock' })
source plugin/remora_nvim.lua
