; Capture Python functions and methods
;
; IMPORTANT: Methods (nested inside classes) come FIRST.
; This ensures we capture @method.def before the more general @function.def
; matches the same nodes.

; Methods: functions defined inside class bodies
(class_definition
  body: (block
    (function_definition
      name: (identifier) @method.name
    ) @method.def
  )
)

; Standalone functions: top-level function definitions
(function_definition
  name: (identifier) @function.name
) @function.def
