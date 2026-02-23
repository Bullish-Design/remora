; Capture TOML tables
;
; Standard tables: [project], [tool.pytest], etc.
; Array tables: [[tool.mypy.overrides]], [[servers]], etc.

; Standard table with simple key: [project]
(table
  (bare_key) @table.name
) @table.def

; Standard table with dotted key: [tool.pytest]
(table
  (dotted_key) @table.name
) @table.def

; Array table with simple key: [[servers]]
(table_array_element
  (bare_key) @array_table.name
) @array_table.def

; Array table with dotted key: [[tool.mypy.overrides]]
(table_array_element
  (dotted_key) @array_table.name
) @array_table.def
