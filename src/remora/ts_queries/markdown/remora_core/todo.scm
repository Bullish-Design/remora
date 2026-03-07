; Capture checkbox list items (task list items)
;
; - [ ] Unchecked task
; - [x] Checked task

(list_item
  [(task_list_marker_unchecked) (task_list_marker_checked)]
  (paragraph
    (inline) @todo.name)) @todo.def
