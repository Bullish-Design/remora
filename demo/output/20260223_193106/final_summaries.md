## demo_config.toml

### File Summary

    The File Root defines a Python project named "ast-summary" with version 0.1.0, specifying its dependencies and development tools. It requires Pydantic and Tree-sitter for core functionality, includes optional tools like pytest and ruff for testing and code formatting, and configures both to align with Python 3.13 and a 120-character line length.

### Nodes

- Document: File Root
    Summary:
        The File Root defines a Python project named "ast-summary" with version 0.1.0, specifying its dependencies and development tools. It requires Pydantic and Tree-sitter for core functionality, includes optional tools like pytest and ruff for testing and code formatting, and configures both to align with Python 3.13 and a 120-character line length.
    - Table: table
        Summary:
            This configuration defines a Python project named "ast-summary" with version 0.1.0, describing it as an AST Summary Demo and requiring Python 3.13 or higher.
    - Table: table
        Summary:
            This configuration specifies the required dependencies for the project, including Pydantic (version 2.0 or higher) for data validation and Tree-sitter (version 0.24 or higher) for parsing and analyzing source code syntax.
    - Table: table
        Summary:
            This section specifies optional dependencies for development, including pytest for testing and ruff for code formatting and linting.
    - Table: table
        Summary:
            Configures Pytest to use auto asyncio mode and specifies the test paths as "tests".
    - Table: table
        Summary:
            Configures Ruff to enforce a line length of 120 characters and target Python 3.13.

## demo_math.py

### File Summary

    The File Root module serves as the entry point for a basic arithmetic application, orchestrating the execution of mathematical operations through the Calculator class, which provides core arithmetic functionality and error handling, and demonstrating its use via the main function that performs and displays a simple addition operation.

### Nodes

- Module: File Root
    Summary:
        The File Root module serves as the entry point for a basic arithmetic application, orchestrating the execution of mathematical operations through the Calculator class, which provides core arithmetic functionality and error handling, and demonstrating its use via the main function that performs and displays a simple addition operation.
    - ClassDef: Calculator
        Summary:
            The Calculator class provides basic arithmetic operations—addition, subtraction, multiplication, and division—by implementing methods that take two integer inputs and return the computed result, with division including error handling for zero divisors. Its child methods collectively enable fundamental mathematical computations through a simple, reusable interface.
        - FunctionDef: __init__
            Summary:
                Initializes an object with a value set to 0.
        - FunctionDef: add
            Summary:
                This method takes two integer inputs and returns their sum.
        - FunctionDef: subtract
            Summary:
                This method subtracts integer y from integer x and returns the result.
        - FunctionDef: multiply
            Summary:
                This method multiplies two integer inputs and returns their product.
        - FunctionDef: divide
            Summary:
                This method divides two integers and returns a float, raising a ValueError if the divisor is zero.
    - FunctionDef: main
        Summary:
            The main function initializes a Calculator instance, adds 5 and 3 using its add method, and prints the result.

## demo_readme.md

### File Summary

    The File Root orchestrates the presentation and functionality of the AST Summary Demo by structuring content around key sections: introducing the AST Summary feature, detailing the engine's code analysis process, and outlining its core capabilities such as multi-format parsing, recursive summarization, real-time monitoring, and isolated environment execution. Its children collectively enable a comprehensive, structured exploration of Python code's syntax and semantics through systematic breakdown and visualization.

### Nodes

- Document: File Root
    Summary:
        The File Root orchestrates the presentation and functionality of the AST Summary Demo by structuring content around key sections: introducing the AST Summary feature, detailing the engine's code analysis process, and outlining its core capabilities such as multi-format parsing, recursive summarization, real-time monitoring, and isolated environment execution. Its children collectively enable a comprehensive, structured exploration of Python code's syntax and semantics through systematic breakdown and visualization.
    - Heading1: AST Summary Demo
        Summary:
            The Heading1 element "AST Summary Demo" introduces the AST Summary feature, which uses child components to extract and present a structured overview of Python code's components and logical flow. Its children illustrate how the feature analyzes and summarizes syntax and semantics to provide a clear, high-level understanding of the code.
        - Paragraph: paragraph
            Summary:
                The code demonstrates the AST (Abstract Syntax Tree) Summary feature, which extracts and summarizes key structural and semantic information from Python code to provide an overview of its components and logic.
    - Heading2: Overview
        Summary:
            The "Overview" heading introduces the core functionality of the AST Summary Engine, which analyzes source code by converting it into an abstract syntax tree and generating structured summaries through tree traversal. The child summary explains how the engine processes code to produce these structured insights.
        - Paragraph: paragraph
            Summary:
                The AST Summary Engine analyzes source code by converting it into an abstract syntax tree (AST) and generates structured summaries by traversing the tree from leaves to root.
    - Heading2: Features
        Summary:
            The "Features" heading outlines the core capabilities of the system, which include parsing multiple file formats, generating recursive summaries, providing real-time progress monitoring, and executing isolated workspace environments for each node. Its children detail how each functionality is implemented and integrated into the overall workflow.
        - List: list
            Summary:
                Parses Python, TOML, and Markdown files, generates recursive summaries, provides a live dashboard to monitor progress, and runs isolated Cairn workspaces for each node.

### Final Overview

Successful: 3
Errors: 0