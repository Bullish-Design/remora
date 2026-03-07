; Capture Markdown sections (heading + paragraphs + subsections)
;
; # Section
; paragraph text...
; ## Subsection
; more text...

(section
  (atx_heading
    (inline) @section.name)) @section.def

; Capture individual headings (just the heading line)
;
; # Heading 1
; ## Heading 2
; ### Heading 3

(atx_heading
  (inline) @heading.name
) @heading.def

; Capture fenced code blocks
; ```python
; code here
; ```

(fenced_code_block
  (info_string)? @code_block.lang
) @code_block.def
