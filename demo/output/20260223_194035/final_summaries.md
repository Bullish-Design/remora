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

    The File Root module provides access to the remora package's built-in queries directory and orchestrates the discovery and analysis of source code by coordinating the TreeSitterDiscoverer's directory traversal, language-specific query loading, file grouping, and parallel parsing to efficiently extract and deduplicate CST nodes.

### Nodes

- Module: File Root
    Summary:
        The File Root module provides access to the remora package's built-in queries directory and orchestrates the discovery and analysis of source code by coordinating the TreeSitterDiscoverer's directory traversal, language-specific query loading, file grouping, and parallel parsing to efficiently extract and deduplicate CST nodes.
    - FunctionDef: _default_query_dir
        Summary:
            Returns the path to the built-in queries directory within the remora package.
    - ClassDef: TreeSitterDiscoverer
        Summary:
            The TreeSitterDiscoverer identifies and parses source files in specified languages by collecting matching files from root directories, loading language-specific queries, and parallelizing the parsing process to extract and deduplicate CST nodes. Its children handle directory traversal, language configuration, file grouping, and parallel parsing to efficiently discover and analyze source code.
        - FunctionDef: __init__
            Summary:
                Initializes the discoverer by resolving root directories, setting query pack and directory, and configuring language support, with optional event emission and language overrides.
        - FunctionDef: discover
            Summary:
                The function discovers and parses source files in specified languages by grouping them by file extension, loading language-specific queries, parsing each file in parallel using tree-sitter, and extracting CST nodes while deduplicating results by node ID.
        - FunctionDef: _collect_files
            Summary:
                Collects files from specified root directories that have extensions matching the given set, returning a sorted list of Path objects.

## match_extractor.py

### File Summary

    The File Root module orchestrates the extraction and deduplication of CST nodes from source files using the MatchExtractor class, which analyzes the parsed tree structure through compiled queries to identify, capture, and organize nodes with metadata such as type, name, and location. Its child component enables precise, pattern-based node extraction and structuring, forming the foundation for downstream code analysis.

### Nodes

- Module: File Root
    Summary:
        The File Root module orchestrates the extraction and deduplication of CST nodes from source files using the MatchExtractor class, which analyzes the parsed tree structure through compiled queries to identify, capture, and organize nodes with metadata such as type, name, and location. Its child component enables precise, pattern-based node extraction and structuring, forming the foundation for downstream code analysis.
    - ClassDef: MatchExtractor
        Summary:
            The MatchExtractor class identifies and deduplicates CST nodes from a source file by executing compiled queries on the parsed tree, leveraging child functions to extract nodes based on capture patterns and construct structured node objects with metadata like type, name, and location.
        - FunctionDef: extract
            Summary:
                Extracts and deduplicates CSTNodes from a source file by running multiple compiled queries against a parsed tree, returning a sorted list of unique nodes.
        - FunctionDef: _run_query
            Summary:
                This function runs a query on a given source file's CST tree, extracts matching nodes based on capture patterns (e.g., @function.def, @function.name), and constructs CSTNode objects with their type, name, file path, and byte range, using the query file name to determine the expected node type.

## query_loader.py

### File Summary

    The File Root module orchestrates the loading and compilation of SCM-formatted query files by leveraging the QueryLoader to parse and structure queries via Tree-sitter, and the CompiledQuery to store and manage query metadata for efficient retrieval and execution.

### Nodes

- Module: File Root
    Summary:
        The File Root module orchestrates the loading and compilation of SCM-formatted query files by leveraging the QueryLoader to parse and structure queries via Tree-sitter, and the CompiledQuery to store and manage query metadata for efficient retrieval and execution.
    - ClassDef: CompiledQuery
        Summary:
            The CompiledQuery class stores and manages query metadata such as query text, source file path, and query name, with its children providing the necessary initialization and attribute assignment to enable query compilation and retrieval.
        - FunctionDef: __init__
            Summary:
                Initializes a class with query data, source file path, query text, and query name, storing them as instance attributes.
    - ClassDef: QueryLoader
        Summary:
            The QueryLoader class loads and compiles SCM-formatted query files from a directory structure using Tree-sitter, leveraging its child components to parse individual .scm files into structured Query objects for use in query execution.
        - FunctionDef: load_query_pack
            Summary:
                Loads and compiles SCM-formatted query files from a specified directory structure using the Tree-sitter grammar for the given language, returning a list of compiled queries.
        - FunctionDef: _compile_query
            Summary:
                Compiles a tree-sitter query from a .scm file by reading its content and parsing it into a tree-sitter Query object, returning a CompiledQuery with the parsed query, source file path, query text, and query name.

## source_parser.py

### File Summary

    The File Root module serves as the central entry point for source code analysis, orchestrating the parsing of source files or raw bytes into structured tree representations. It leverages the SourceParser class to initialize and manage grammar-based parsing, enabling robust and flexible analysis of source code through its file and byte-level parsing capabilities.

### Nodes

- Module: File Root
    Summary:
        The File Root module serves as the central entry point for source code analysis, orchestrating the parsing of source files or raw bytes into structured tree representations. It leverages the SourceParser class to initialize and manage grammar-based parsing, enabling robust and flexible analysis of source code through its file and byte-level parsing capabilities.
    - ClassDef: SourceParser
        Summary:
            The SourceParser class initializes a Tree-sitter parser from a grammar module and provides methods to parse source files or raw bytes into a tree structure, with children handling grammar setup, file parsing, and byte-level parsing for robust and flexible source code analysis.
        - FunctionDef: __init__
            Summary:
                Initializes the parser with a specified Tree-sitter grammar module by importing the module and creating a Language and Parser instance from it.
        - FunctionDef: parse_file
            Summary:
                Parses a source file into a tree structure and returns the parsed tree along with the raw source bytes, handling read errors and warning about parse errors.
        - FunctionDef: parse_bytes
            Summary:
                Parses raw bytes into a Tree object using the underlying parser, useful for testing without file I/O.

### Final Overview

Successful: 6
Errors: 0