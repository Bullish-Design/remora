# Future Enhancements

This document details potential enhancements to the tree-sitter discovery pipeline that were intentionally excluded from the V2 refactor to keep scope manageable. Each section describes:

1. **What it is** — A description of the enhancement
2. **Why it's beneficial** — The problems it solves and gains it provides
3. **When to implement** — Signals and scenarios that indicate it's time to add this enhancement

---

## 1. Parallelism

### What It Is

Parallel file parsing that processes multiple Python files concurrently using `concurrent.futures.ThreadPoolExecutor`. Each thread maintains its own `SourceParser` instance since tree-sitter `Parser` objects are not thread-safe.

### Benefits

**Performance gains on multi-core systems:**
- File I/O and parsing are CPU-bound operations that can benefit significantly from parallelism
- Reduces total discovery time from `O(n)` to roughly `O(n/workers)` for large codebases
- Particularly impactful during initial project scan or full rebuilds

**Improved user experience:**
- Faster startup times for the analyzer
- More responsive IDE-like tools that rely on discovery
- Better scaling as codebase size grows

**Resource utilization:**
- Makes use of idle CPU cores during discovery phase
- Since parsing is largely independent per file, parallelism is a natural fit

### When to Implement

**You're likely ready when you notice:**

1. **Discovery takes >5 seconds on typical hardware** — If `discover()` consistently takes multiple seconds even on SSDs, users will feel the lag

2. **Large codebase scenarios:**
   - Projects with 1000+ Python files
   - Monorepos with mixed Python code across many directories
   - CI pipelines where discovery is part of the critical path

3. **User complaints about slow startup:**
   - "Why does remora take so long to start?"
   - Reports of timeout issues on discovery

4. **Profiling shows discovery is the bottleneck:**
   - Discovery phase dominates execution time
   - CPU usage is low during discovery (indicating sequential work)

5. **You need to support large file trees:**
   - Enterprise codebases
   - Generated code scenarios (thousands of auto-generated files)

**Implementation notes:**
- Use `ThreadPoolExecutor` not `ProcessPoolExecutor` (parsing is GIL-releasing)
- Each thread needs its own `SourceParser()` instance
- Consider `max_workers=os.cpu_count()` or slightly less to avoid thrashing
- Deduplication and sorting must happen after all threads complete

---

## 2. Tree Caching

### What It Is

A caching layer in `SourceParser` that stores parsed tree-sitter Trees keyed by `(file_path, mtime)`. Files are only re-parsed if their modification time has changed since the last parse.

### Benefits

**Dramatically faster incremental operations:**
- Subsequent discoveries on unchanged files are nearly instant
- Changes the complexity from `O(total_files)` to `O(changed_files)`
- Critical for watch-mode scenarios or repeated analysis runs

**Reduced CPU usage:**
- Parsing is one of the most expensive operations in the pipeline
- Avoids redundant work during iterative development workflows

**Memory tradeoff is usually favorable:**
- Tree objects are relatively compact compared to source text
- Cache can be bounded (LRU) to prevent unbounded growth
- Cache hits avoid both disk I/O and CPU parsing

### When to Implement

**You're likely ready when you notice:**

1. **Repeated discoveries on the same files:**
   - Watch mode that re-runs discovery on file changes
   - CI pipelines that run analysis multiple times
   - IDE integrations that query discovery frequently

2. **User reports of slowness on second run:**
   - "Why is it just as slow the second time?"
   - Users expect caching for unchanged files

3. **Large files that change infrequently:**
   - Auto-generated files (protobuf, API specs)
   - Third-party vendored code
   - Stable library code

4. **Memory pressure is not a concern:**
   - You have RAM to spare
   - Trees are smaller than you expected

5. **Need for sub-second repeated discoveries:**
   - Real-time analysis scenarios
   - Interactive tools requiring rapid feedback

**Implementation notes:**
- Cache key: `(resolved_path, st_mtime)` tuple
- Use `functools.lru_cache` with bounded size, or dict with TTL
- Consider cache invalidation on file deletion/rename
- Memory usage scales with number of unique files parsed

---

## 3. Incremental Discovery

### What It Is

An enhancement to `TreeSitterDiscoverer` that tracks file modification times between runs and only re-processes changed files. Builds on top of Tree Caching but adds persistence and change tracking.

### Benefits

**Transforms discovery from batch to incremental:**
- Only changed files need re-parsing and re-querying
- Maintains state across process restarts (via file-based storage)
- Enables true "watch mode" with minimal overhead

**Massive time savings for iterative workflows:**
- After initial scan, subsequent discoveries take milliseconds
- Makes remora suitable for real-time IDE integration
- Supports long-running daemon modes

**Scales to very large codebases:**
- Initial scan is still O(n), but everything after is O(changes)
- 10,000 file codebase feels as responsive as 100 file codebase after initial scan

### When to Implement

**You're likely ready when you notice:**

1. **Watch mode is too slow:**
   - File watcher triggers re-discovery that takes seconds
   - Users expect <100ms feedback on file save
   - IDE integration feels sluggish

2. **Frequent small changes:**
   - Developers editing single files
   - Test-driven development workflows
   - Rapid iteration scenarios

3. **Large codebases with localized changes:**
   - Monorepos where you only touch a few files
   - Microservice architectures with many small services
   - Legacy codebases with stable core + changing periphery

4. **Persistent process scenarios:**
   - Language server protocol (LSP) implementation
   - Long-running analysis daemons
   - Server-mode remora

5. **Comparison with other tools:**
   - Users compare remora to tools with incremental parsing (like Pyright, mypy daemon)
   - Competitors offer faster incremental analysis

**Implementation notes:**
- Store state in `.remora/cache/` or similar
- Track `{file_path: mtime, node_ids: [...]}` mapping
- On run: compare mtimes, re-parse changed files only
- Handle file deletion (remove from cache and node list)
- Consider cache invalidation on query file changes

---

## 4. Multi-Language Support

### What It Is

Extending the discovery pipeline to support languages beyond Python by:
- Making `SourceParser` language-aware (accepting a language parameter)
- Loading appropriate tree-sitter language bindings dynamically
- Leveraging the existing `QueryLoader` language subdirectory structure

### Benefits

**Unified codebase analysis:**
- Single tool analyzes Python, JavaScript, TypeScript, Go, Rust, etc.
- Consistent node discovery across all languages
- Cross-language project support (e.g., Python backend + TS frontend)

**Codebase-wide insights:**
- Find all function definitions across a polyglot project
- Consistent naming conventions across languages
- Cross-language dependency analysis

**Future-proof architecture:**
- Positions remora as a universal code analysis tool
- Leverages tree-sitter's extensive language support
- Plugin-like architecture for new languages

**Reduced tool fragmentation:**
- One discovery pipeline instead of language-specific tools
- Shared configuration and query format
- Consistent output format (CSTNode) across languages

### When to Implement

**You're likely ready when you notice:**

1. **User requests for other languages:**
   - "Can remora analyze my JavaScript code too?"
   - Feature requests for TypeScript/Go/Rust support
   - Issues filed about non-Python files being ignored

2. **Polyglot codebases in your user base:**
   - Full-stack projects (Python backend + JS frontend)
   - Microservices in multiple languages
   - Codebases transitioning between languages

3. **Competitive pressure:**
   - Other tools support multiple languages
   - Users choosing tools based on language breadth
   - Enterprise requirements for polyglot analysis

4. **Architecture is ready:**
   - QueryLoader already has language subdirectories
   - NodeType enum can be extended
   - Tree-sitter has mature parsers for target languages

5. **Specific use cases emerge:**
   - Need to analyze TypeScript type definitions alongside Python
   - Documentation generation across language boundaries
   - API contract checking between Python and other languages

**Implementation notes:**
- `SourceParser` constructor takes `language: str` parameter
- Dynamically import `tree-sitter-{language}` packages
- Map language to parser in a registry dict
- Queries already organized as `queries/{language}/{pack}/`
- NodeType may need language-specific variants or stay generic

---

## Summary: Priority Recommendations

**Start with Parallelism if:**
- You have large codebases (1000+ files)
- Discovery is currently slow (>2 seconds)
- Users report performance issues

**Start with Tree Caching if:**
- You're implementing watch mode
- Running discovery multiple times per session
- CPU profiling shows redundant parsing

**Start with Incremental Discovery if:**
- Building long-running daemon or LSP server
- Watch mode with caching is still too slow
- Working with very large codebases (10k+ files)

**Start with Multi-Language Support if:**
- Clear user demand for other languages
- Polyglot projects are common in your user base
- Positioning remora as a universal tool

---

## Technical Debt Prevention

When implementing these enhancements, watch for:

1. **Cache consistency bugs:** — Always invalidate when in doubt
2. **Thread safety issues:** — Parsers are not thread-safe, results may be
3. **Memory leaks:** — Unbounded caches grow indefinitely
4. **Language detection edge cases:** — `.h` files could be C or C++
5. **Cross-platform path handling:** — Windows vs Unix path formats in cache keys

Each enhancement adds complexity. Implement only when the pain is real, not anticipated.
