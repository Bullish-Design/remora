check-arch:
    devenv shell -- tach check

check-arch-slo:
    devenv shell -- python scripts/check_arch_slo.py

check:
    just check-arch
    just check-arch-slo
