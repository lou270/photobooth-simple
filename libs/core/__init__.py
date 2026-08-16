"""Session orchestration, independent of any UI framework.

Nothing here imports Kivy: this is the logic that decides what the booth does,
kept testable on its own so a change of front-end never touches it.
"""

from libs.core.process_runner import ProcessRunner
from libs.core.storage import SessionStorage

__all__ = ['ProcessRunner', 'SessionStorage']
