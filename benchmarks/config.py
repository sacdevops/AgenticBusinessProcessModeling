"""Benchmark configuration."""
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"

NOTATION_MODES = ["XML", "JSON", "LION"]
REPETITIONS = 30
MAX_WORKERS = 5

BENCHMARK_SETTINGS = {
    "timeout_seconds": 180,
}

LION_SCHEMA_MAPPINGS = {
    'participate': {
        'x': 'x', 'y': 'y', 'w': 'width', 'h': 'height',
        'label': 'label', 'id': 'elementId', 'expanded': 'isExpanded',
        'lanes': 'lanes',
    },
    'draw': {
        'type': 'elementType', 'x': 'x', 'y': 'y', 'label': 'label',
        'id': 'elementId', 'parent': 'parentId', 'connectTo': 'connectTo',
        'eventDef': 'eventDefinition',
    },
    'connect': {'src': 'sourceId', 'tgt': 'targetId', 'label': 'label'},
    'rename': {'id': 'elementId', 'label': 'label'},
    'move': {'id': 'elementId', 'x': 'x', 'y': 'y'},
    'resize': {'id': 'elementId', 'w': 'width', 'h': 'height'},
    'update': {'id': 'elementId', 'prop': 'property', 'val': 'value'},
}

ACTION_ORDER = ['delete', 'resize', 'move', 'participate', 'draw', 'rename', 'update', 'connect']
