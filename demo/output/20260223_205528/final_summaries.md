## __init__.py

### File Summary

    This module provides tree-sitter-based node discovery functionality for Remora, enabling the extraction and matching of code structure nodes using syntax trees, with support for queries, parsing, and node identification.

### Nodes

- Module: File Root
    Summary:
        This module provides tree-sitter-based node discovery functionality for Remora, enabling the extraction and matching of code structure nodes using syntax trees, with support for queries, parsing, and node identification.

## models.py

### File Summary

    The File Root module provides error handling and file hashing capabilities for consistent file identification. It uses a custom exception class to manage discovery errors and computes a stable SHA-256 hash of file metadata to ensure consistency across reformatting.

### Nodes

- Module: File Root
    Summary:
        The File Root module provides error handling and file hashing capabilities for consistent file identification. It uses a custom exception class to manage discovery errors and computes a stable SHA-256 hash of file metadata to ensure consistency across reformatting.
    - ClassDef: DiscoveryError
        Summary:
            A custom exception class for discovery-related errors, inheriting from BaseDiscoveryError.
    - FunctionDef: compute_node_id
        Summary:
            Computes a stable, 16-character hexadecimal SHA-256 hash of a file path, node type, and name, ensuring consistency across reformatting by excluding byte offsets.

## discoverer.py

### File Summary

    The File Root module provides access to the remora package's built-in queries directory and enables source file discovery and parsing using TreeSitter, with child components handling file location, language configuration, and CST node extraction through query packs.

### Nodes

- Module: File Root
    Summary:
        The File Root module provides access to the remora package's built-in queries directory and enables source file discovery and parsing using TreeSitter, with child components handling file location, language configuration, and CST node extraction through query packs.
    - FunctionDef: _default_query_dir
        Summary:
            Returns the path to the built-in queries directory inside the remora package.
    - ClassDef: TreeSitterDiscoverer
        Summary:
            The TreeSitterDiscoverer identifies and parses source files from root directories using tree-sitter grammars, extracting and deduplicating CST nodes by language and file extension, leveraging child functions to locate files, configure language support, and apply query packs for node extraction.
        - FunctionDef: __init__
            Summary:
                Initializes the discoverer by resolving root directories, setting query pack and directory, and configuring language support, with optional event emission and language overrides.
        - FunctionDef: discover
            Summary:
                The function discovers and extracts CST nodes from source files by iterating over configured languages, grouping files by extension, parsing them with tree-sitter grammars, and applying query packs to extract relevant nodes, while deduplicating results by node ID.
        - FunctionDef: _collect_files
            Summary:
                Collects files from specified root directories that have extensions matching the given set, returning a sorted list of Path objects.

## query_loader.py

### File Summary

    The File Root module orchestrates the management and execution of SCM queries by storing query metadata via the CompiledQuery class and loading compiled queries from source files using the QueryLoader class, enabling structured query processing and analysis.

### Nodes

- Module: File Root
    Summary:
        The File Root module orchestrates the management and execution of SCM queries by storing query metadata via the CompiledQuery class and loading compiled queries from source files using the QueryLoader class, enabling structured query processing and analysis.
    - ClassDef: CompiledQuery
        Summary:
            The CompiledQuery class stores query metadata such as query text, source file path, and query name, initializing these values as instance attributes to enable structured query management and retrieval. Its children provide the foundational data attributes necessary for query compilation and subsequent execution.
        - FunctionDef: __init__
            Summary:
                Initializes an object with query data, source file path, query text, and query name, storing them as instance attributes.
    - ClassDef: QueryLoader
        Summary:
            The QueryLoader class loads and compiles SCM query files from a directory structure using Tree-sitter, leveraging its child methods to parse individual .scm files into structured Query objects for use in language analysis.
        - FunctionDef: load_query_pack
            Summary:
                Loads and compiles SCM query files from a specified directory structure using the Tree-sitter grammar for a given language, returning a list of compiled queries.
        - FunctionDef: _compile_query
            Summary:
                Compiles a tree-sitter query from a .scm file by reading its content and parsing it into a tree-sitter Query object, returning a CompiledQuery with the parsed query, source file path, query text, and query name.

## match_extractor.py

### File Summary

    The File Root module orchestrates the extraction and deduplication of CST nodes from source files by leveraging the MatchExtractor class, which processes multiple compiled queries to identify, construct, and organize nodes based on capture patterns, then sorts them by file path, byte position, node type, and name. Its children enable precise, efficient parsing and structuring of code elements for downstream analysis.

### Nodes

- Module: File Root
    Summary:
        The File Root module orchestrates the extraction and deduplication of CST nodes from source files by leveraging the MatchExtractor class, which processes multiple compiled queries to identify, construct, and organize nodes based on capture patterns, then sorts them by file path, byte position, node type, and name. Its children enable precise, efficient parsing and structuring of code elements for downstream analysis.
    - ClassDef: MatchExtractor
        Summary:
            The MatchExtractor class extracts and deduplicates CST nodes from parsed source files using multiple compiled queries, with its child functions handling individual query execution and node construction based on capture patterns, then sorting the results by file path, byte position, node type, and name.
        - FunctionDef: extract
            Summary:
                Runs multiple compiled queries on a parsed tree to extract and deduplicate CSTNodes, then returns them sorted by file path, start byte, node type, and name.
        - FunctionDef: _run_query
            Summary:
                This function runs a query on a given source file's CST tree, extracts matching nodes based on capture patterns (e.g., @function.def, @function.name), and constructs CSTNode objects with their type, name, file path, and byte range, using the query filename to determine the expected node type.

## source_parser.py

### File Summary

    The File Root module serves as the central entry point for processing source code, orchestrating the parsing workflow through the SourceParser class, which uses tree-sitter grammars to robustly parse files or raw bytes into structured tree representations, with its child components managing grammar setup, file parsing, and error handling.

### Nodes

- Module: File Root
    Summary:
        The File Root module serves as the central entry point for processing source code, orchestrating the parsing workflow through the SourceParser class, which uses tree-sitter grammars to robustly parse files or raw bytes into structured tree representations, with its child components managing grammar setup, file parsing, and error handling.
    - ClassDef: SourceParser
        Summary:
            The SourceParser class provides a unified interface for parsing source code into a tree structure, leveraging tree-sitter grammars to parse either files or raw bytes, with child components handling grammar initialization, file parsing, and byte-level parsing with error resilience.
        - FunctionDef: __init__
            Summary:
                Initializes the parser with a specified Tree-sitter grammar module by importing it and creating a Language and Parser instance from the imported module.
        - FunctionDef: parse_file
            Summary:
                Parses a source file into a tree structure and returns the parsed tree along with the raw source bytes, handling read errors and parse errors with warnings.
        - FunctionDef: parse_bytes
            Summary:
                Parses raw bytes into a Tree object using the underlying parser, useful for testing without file I/O.

### Final Overview

Successful: 6
Errors: 0