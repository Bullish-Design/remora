" Remora Neovim V2.1 Quick Starter
" Copy this to your Neovim config or run with :source

" Quick Setup
function! RemoraSetup()
    " Add demo to lua path
    let demo_path = fnamemodify(expand('<sfile>'), ':p:h') . '/../demo/nvim/lua'
    execute 'set runtimepath+=' . demo_path
    
    " Register LSP
    lua require('remora_starter').setup()
    
    echo "Remora V2.1 setup complete!"
endfunction

" Start LSP
function! RemoraStart()
    lua vim.cmd("RemoraStart")
endfunction

" Stop LSP  
function! RemoraStop()
    lua vim.cmd("RemoraStop")
endfunction

" Toggle Panel
function! RemoraTogglePanel()
    lua vim.cmd("RemoraTogglePanel")
endfunction

" Chat
function! RemoraChat()
    lua vim.cmd("RemoraChat")
endfunction

" Rewrite
function! RemoraRewrite()
    lua vim.cmd("RemoraRewrite")
endfunction

" Accept
function! RemoraAccept()
    lua vim.cmd("RemoraAccept")
endfunction

" Reject
function! RemoraReject()
    lua vim.cmd("RemoraReject")
endfunction

" Status
function! RemoraStatus()
    lua vim.cmd("RemoraStatus")
endfunction

" Parse current file
function! RemoraParse()
    lua vim.cmd("RemoraParse")
endfunction

" Commands
command! RemoraSetup call RemoraSetup()
command! RemoraStart call RemoraStart()
command! RemoraStop call RemoraStop()
command! RemoraTogglePanel call RemoraTogglePanel()
command! RemoraChat call RemoraChat()
command! RemoraRewrite call RemoraRewrite()
command! RemoraAccept call RemoraAccept()
command! RemoraReject call RemoraReject()
command! RemoraStatus call RemoraStatus()
command! RemoraParse call RemoraParse()

echo "Remora V2.1 commands loaded: RemoraSetup, RemoraStart, RemoraStop, RemoraTogglePanel, RemoraChat, RemoraRewrite, RemoraAccept, RemoraReject, RemoraStatus, RemoraParse"
