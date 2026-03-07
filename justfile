check-arch:
    devenv shell -- tach check

check-arch-slo:
    devenv shell -- python scripts/check_arch_slo.py

gen-package-graph:
    devenv shell -- python scripts/generate_package_dependency_graph.py

check:
    just check-arch
    just check-arch-slo
