"""Entry point for the Windows application bundle."""
import sys
from albion_trade_desk.__main__ import main

if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.argv.extend(['serve', '--open'])
    raise SystemExit(main())
