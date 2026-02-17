; Capture module-level elements
(module) @file.module

; Capture imports
(import_statement) @file.import
(import_from_statement) @file.import_from

; Capture module docstring (first string literal)
(module
  (expression_statement
    (string) @file.docstring
  )
)
