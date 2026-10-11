// 5×7 pixel font — only the Cyrillic letters the film spells with cubes.
// Every "#" becomes one cube, so the words are built from the same blocks as the mark.
const G = {
  "И": ["#...#", "#..##", "#.#.#", "#.#.#", "##..#", "#...#", "#...#"],
  "Д": [".###.", ".#.#.", ".#.#.", ".#.#.", ".#.#.", "#####", "#...#"],
  "Е": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
  "Я": [".####", "#...#", "#...#", ".####", "..#.#", ".#..#", "#...#"],
  "К": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
  "О": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  "М": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
  "А": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
  "Н": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
  "Г": ["#####", "#....", "#....", "#....", "#....", "#....", "#...."],
  "Т": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
  "-": [".....", ".....", ".....", ".###.", ".....", ".....", "....."],
};

export const GLYPH_W = 5, GLYPH_H = 7;

// Returns [{x, y, col, row, letter}] with the word centred on the origin, y pointing up, one unit = one cube pitch.
export function layoutWord(word) {
  const letters = [...word];
  const cols = letters.length * GLYPH_W + (letters.length - 1);
  const cells = [];
  letters.forEach((ch, li) => {
    const g = G[ch];
    if (!g) throw new Error("no glyph for " + ch);
    for (let r = 0; r < GLYPH_H; r++)
      for (let c = 0; c < GLYPH_W; c++)
        if (g[r][c] === "#") {
          const col = li * (GLYPH_W + 1) + c;
          cells.push({ x: col - (cols - 1) / 2, y: (GLYPH_H - 1) / 2 - r, col, row: r, letter: li });
        }
  });
  return { cells, cols, rows: GLYPH_H };
}

// 16×16 brand mark (173 lit cells), centred on the origin.
export function layoutMark(grid) {
  const cells = [];
  grid.forEach((row, r) => {
    const s = typeof row === "string" ? row : row.map((v) => (v ? "#" : ".")).join("");
    for (let c = 0; c < s.length; c++)
      if (s[c] === "#") cells.push({ x: c - 7.5, y: 7.5 - r, col: c, row: r, letter: 0 });
  });
  return { cells, cols: 16, rows: 16 };
}
