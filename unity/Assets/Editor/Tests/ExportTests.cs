// Checks that Unity itself accepts what the connector exports: the sliced sprite
// sheet, the autotile sheet, and the Rule Tile, which must paint the right tile for
// every cell. The files come from scripts/make_unity_fixtures.py.
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.Tilemaps;

public class ExportTests
{
    const string Folder = "Assets/Sprites/";

    [OneTimeSetUp]
    public void Import()
    {
        AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
    }

    static Sprite[] SpritesIn(string file)
    {
        return AssetDatabase.LoadAllAssetsAtPath(Folder + file).OfType<Sprite>().ToArray();
    }

    [Test]
    public void TheSpriteSheetIsSlicedIntoItsFrames()
    {
        var sprites = SpritesIn("hero.png");
        Assert.AreEqual(4, sprites.Length);
        foreach (var sprite in sprites)
        {
            Assert.AreEqual(16f, sprite.rect.width);
            Assert.AreEqual(16f, sprite.rect.height);
        }
        CollectionAssert.AreEquivalent(
            new[] { "hero_0", "hero_1", "hero_2", "hero_3" }, sprites.Select(s => s.name));
    }

    [Test]
    public void TheAutotileSheetHasEveryTile()
    {
        Assert.AreEqual(47, SpritesIn("terrain.png").Length);
    }

    [Test]
    public void TheRuleTileLoadsWithASpriteForEveryRule()
    {
        var rule = AssetDatabase.LoadAssetAtPath<RuleTile>(Folder + "terrain_rule.asset");
        Assert.IsNotNull(rule, "the Rule Tile didn't load");
        Assert.AreEqual(47, rule.m_TilingRules.Count);
        Assert.IsTrue(rule.m_TilingRules.All(r => r.m_Sprites.Length > 0 && r.m_Sprites[0] != null));
    }

    [Test]
    public void TheRuleTilePaintsTheRightTileInEveryCell()
    {
        var rule = AssetDatabase.LoadAssetAtPath<RuleTile>(Folder + "terrain_rule.asset");
        var expected = JsonUtility.FromJson<Expected>(File.ReadAllText(Folder + "terrain_expected.json"));
        var grid = new GameObject("Grid", typeof(Grid));
        try
        {
            var map = new GameObject("Map", typeof(Tilemap)).GetComponent<Tilemap>();
            map.transform.SetParent(grid.transform);
            foreach (var c in expected.cells) map.SetTile(new Vector3Int(c.x, c.y, 0), rule);
            map.RefreshAllTiles();
            foreach (var c in expected.cells)
            {
                var sprite = map.GetSprite(new Vector3Int(c.x, c.y, 0));
                Assert.AreEqual(c.sprite, sprite == null ? "nothing" : sprite.name, $"cell ({c.x}, {c.y})");
            }
        }
        finally
        {
            Object.DestroyImmediate(grid);
        }
    }

    [System.Serializable]
    class Cell
    {
        public int x;
        public int y;
        public string sprite;
    }

    [System.Serializable]
    class Expected
    {
        public Cell[] cells;
    }
}
