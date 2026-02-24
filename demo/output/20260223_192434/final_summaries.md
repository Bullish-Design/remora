## demo_math.py

### File Summary

    The File Root module organizes and executes a basic arithmetic calculator application by leveraging the Calculator class to perform mathematical operations and the main function to demonstrate and display the results of those operations.

### Nodes

- Module: File Root
    Summary:
        The File Root module organizes and executes a basic arithmetic calculator application by leveraging the Calculator class to perform mathematical operations and the main function to demonstrate and display the results of those operations.
    - ClassDef: Calculator
        Summary:
            The Calculator class provides basic arithmetic operations—addition, subtraction, multiplication, and division—by implementing methods that take two integer inputs and return the computed result, with division handling division by zero through a ValueError.
        - FunctionDef: __init__
            Summary:
                Initializes an instance with a value set to 0.
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
                This method divides two integers and returns their quotient as a float, raising a ValueError if the divisor is zero.
    - FunctionDef: main
        Summary:
            The main function initializes a Calculator instance, adds 5 and 3 using its add method, and prints the result.

## demo_config.toml

### File Summary

    The File Root defines a Python project named "ast-summary" with version 0.1.0, specifying its dependencies and development tools. It requires Pydantic and Tree-sitter for core functionality, includes optional tools like pytest and ruff for testing and code formatting, and configures both to align with Python 3.13 and project standards.

### Nodes

- Document: File Root
    Summary:
        The File Root defines a Python project named "ast-summary" with version 0.1.0, specifying its dependencies and development tools. It requires Pydantic and Tree-sitter for core functionality, includes optional tools like pytest and ruff for testing and code formatting, and configures both to align with Python 3.13 and project standards.
    - Table: table
        Summary:
            This configuration defines a Python project named "ast-summary" with version 0.1.0, describing it as an AST Summary Demo and requiring Python 3.13 or higher.
    - Table: table
        Summary:
            This configuration specifies the required dependencies for the project, including Pydantic (version 2.0 or higher) for data validation and Tree-sitter (version 0.24 or higher) for parsing and analyzing programming language syntax.
    - Table: table
        Summary:
            This section specifies optional dependencies for development, including pytest for testing and ruff for code formatting and linting.
    - Table: table
        Summary:
            Configures pytest to use auto asyncio mode and specifies the test paths as "tests".
    - Table: table
        Summary:
            Configures Ruff to enforce a line length of 120 characters and target Python 3.13.

## demo_readme.md

### File Summary

    The File Root orchestrates the AST Summary Engine's core functionality by organizing and presenting its capabilities, including code parsing, recursive summarization, real-time monitoring, and isolated workspace execution, with its children detailing how each feature is implemented and demonstrated.

### Nodes

- Document: File Root
    Summary:
        The File Root orchestrates the AST Summary Engine's core functionality by organizing and presenting its capabilities, including code parsing, recursive summarization, real-time monitoring, and isolated workspace execution, with its children detailing how each feature is implemented and demonstrated.
    - Heading1: AST Summary Demo
        Summary:
            The AST Summary Demo showcases a feature that extracts and summarizes key structural and semantic information from Python code, providing an overview of its components through the analysis of its abstract syntax tree. Its child element explains how the AST Summary feature works by demonstrating the extraction and presentation of structural and semantic details from the code.
        - Paragraph: paragraph
            Summary:
                The code demonstrates the AST (Abstract Syntax Tree) Summary feature, which extracts and summarizes key structural and semantic information from Python code to provide an overview of its structure and components.
    - Heading2: Overview
        Summary:
            The "Overview" heading introduces the core functionality of the AST Summary Engine, which analyzes source code by converting it into an abstract syntax tree and generating structured summaries through tree traversal. The child summary explains how the engine processes code to produce these structured insights.
        - Paragraph: paragraph
            Summary:
                The AST Summary Engine analyzes source code by converting it into an abstract syntax tree (AST) and generates structured summaries by traversing the tree from leaves to root.
    - Heading2: Features
        Summary:
            The "Features" heading outlines the core capabilities of the system, which include parsing multiple file formats, generating recursive summaries, providing real-time progress monitoring, and executing isolated workspaces for each node—functions enabled by its child components.
        - List: list
            Summary:
                Parses Python, TOML, and Markdown files, generates recursive summaries, provides a live dashboard to monitor progress, and runs isolated Cairn workspaces for each node.

### Final Overview

Successful: 3
Errors: 0