; Capture function definitions
(function_definition
  name: (identifier) @function.name
) @function.def

; Capture async function definitions
(function_definition
  "async"
  name: (identifier) @async_function.name
) @async_function.def
