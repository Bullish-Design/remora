; Capture Markdown sections (ATX headings)
;
; # Heading 1
; ## Heading 2
; ### Heading 3
; etc.

(atx_heading
  (inline) @section.name
) @section.def

; Capture fenced code blocks
; ```python
; code here
; ```

(fenced_code_block
  (info_string)? @code_block.lang
) @code_block.def
