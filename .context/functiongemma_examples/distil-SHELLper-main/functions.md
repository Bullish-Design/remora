# Task Format

We use the Gorilla file system tool format for inputs. The model outputs bash commands:

| Gorilla Tool | Arguments | Bash Translation |
|-------------|-----------|------------------|
| `cat` | file_name | `cat file_name` |
| `cd` | folder | `cd folder` |
| `cp` | source, destination | `cp -r source destination` |
| `diff` | file_name1, file_name2 | `diff file_name1 file_name2` |
| `du` | human_readable (boolean) | `du` or `du -h` |
| `echo` | content | `echo "content"` |
| `echo` | content, file_name | `echo "content" >> file_name` |
| `find` | path, name | `find path -name '*name*'` |
| `find` | path | `find path` |
| `grep` | file_name, pattern | `grep "pattern" file_name` |
| `ls` | a (boolean) | `ls` or `ls -a` |
| `mkdir` | dir_name | `mkdir dir_name` |
| `mv` | source, destination | `mv source destination` |
| `pwd` | (none) | `pwd` |
| `rm` | file_name | `rm file_name` (or `rm -r` with `--allow_recursive`) |
| `rmdir` | dir_name | `rmdir dir_name` |
| `sort` | file_name | `sort file_name` |
| `tail` | file_name, lines | `tail -n lines file_name` |
| `touch` | file_name | `touch file_name` |
| `wc` | file_name, mode | `wc -mode file_name` (mode: l/w/c) |
