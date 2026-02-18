; Capture function definitions
(function_definition
  name: (identifier) @function.name
) @function.def

; Capture async function definitions
(function_definition
  "async"
  name: (identifier) @function.name
) @function.def
