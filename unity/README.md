# Unity check

A small Unity project that imports what the connector exports, so Unity itself says
whether it accepts them:

- a sprite sheet with its sliced `.meta` (four 16×16 frames, named `hero_0`…`hero_3`)
- a 47-tile autotile sheet from `make_autotiles`, sliced the same way
- its Rule Tile, which must load and paint the right tile in every cell of a block

The files are generated fresh by `scripts/make_unity_fixtures.py` from the same code as
the real exports, and the checks are EditMode tests in `Assets/Editor/Tests`. The
`Unity` workflow runs them with [GameCI](https://game.ci) on Unity 2022.3 LTS.

## Turning it on

Unity won't run without a licence, so the workflow skips itself until the repository
has one. A free Unity Personal licence works:

1. Follow GameCI's [activation guide](https://game.ci/docs/github/activation) for a
   Personal licence. It ends with three repository secrets: `UNITY_LICENSE`,
   `UNITY_EMAIL`, and `UNITY_PASSWORD`.
2. Run the `Unity` workflow from the Actions tab.

These are secrets in the repository settings, never files: nothing about the licence
is committed.

## Running it yourself

Open this folder in Unity 2022.3, run `python scripts/make_unity_fixtures.py
unity/Assets/Sprites` from the repository root, and run the tests from
**Window → General → Test Runner → EditMode**.
