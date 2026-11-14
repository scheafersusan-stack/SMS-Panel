"""``python -m payamakyar.api serve|worker|migrate|create-admin`` (see ``cli``)."""

import sys

from payamakyar.api.cli import main

if __name__ == "__main__":
    sys.exit(main())
