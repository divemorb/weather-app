/* sky.js — the animated sky's particles (step A3b).
 *
 * The sky layer ([data-test=sky], index.html) shows the scene named on
 * <html data-scene> (app.js, from format.js scene()). The static parts
 * (sun, moon, clouds, fog, lightning) are in the markup; the many
 * small parts — stars, wind streaks, raindrops, snowflakes, hailstones
 * — are generated here once at startup, with a fixed count and random
 * positions and timings. sky.css animates them, but only while the
 * user has not asked for reduced motion; everything stays inside the
 * fixed sky layer, behind the tiles.
 */

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function scatter(container, count, make) {
  for (let i = 0; i < count; i++) {
    const el = document.createElement("span");
    make(el, i);
    container.appendChild(el);
  }
}

export function initSky() {
  const stars = document.getElementById("sky-stars");
  if (!stars) return;
  /* The night sky: small dots that twinkle (a negative delay puts every
   * star mid-twinkle right after the page loads). */
  scatter(stars, 120, (el) => {
    const size = rand(3, 6.5);
    el.className = "star";
    el.style.left = `${rand(0, 100)}%`;
    el.style.top = `${rand(0, 62)}%`;
    el.style.width = `${size}px`;
    el.style.height = `${size}px`;
    el.style.animationDuration = `${rand(2, 4.2)}s`;
    el.style.animationDelay = `${rand(-4, 0)}s`;
  });
  /* The wind scene: thin streaks flying across the sky. */
  const streaks = document.getElementById("sky-streaks");
  scatter(streaks, 12, (el) => {
    el.className = "streak";
    el.style.top = `${rand(4, 78)}%`;
    el.style.width = `${rand(180, 420)}px`;
    el.style.animationDuration = `${rand(2.2, 4)}s`;
    el.style.animationDelay = `${rand(-4, 0)}s`;
  });
  /* Rain: short fast streaks; the .drop-extra ones show only in the
   * heavy-rain scene (a denser, faster rain). */
  const rain = document.getElementById("sky-rain");
  scatter(rain, 48, (el) => {
    el.className = "drop";
    el.style.left = `${rand(0, 99.5)}%`;
    el.style.animationDuration = `${rand(0.7, 1.15)}s`;
    el.style.animationDelay = `${rand(-1.1, 0)}s`;
  });
  scatter(rain, 32, (el) => {
    el.className = "drop drop-extra";
    el.style.left = `${rand(0, 99.5)}%`;
    el.style.animationDuration = `${rand(0.5, 0.85)}s`;
    el.style.animationDelay = `${rand(-0.9, 0)}s`;
  });
  /* Snow: a few larger flakes that fall with a sideways sway. */
  const snow = document.getElementById("sky-snow");
  scatter(snow, 50, (el) => {
    const size = rand(5, 9);
    el.className = "flake";
    el.style.left = `${rand(0, 99.5)}%`;
    el.style.width = `${size}px`;
    el.style.height = `${size}px`;
    el.style.animationDuration = `${rand(1.3, 2.4)}s`;
    el.style.animationDelay = `${rand(-2.4, 0)}s`;
  });
  /* Hail: small stones, fast; the duration spans the whole fall-and-bounce
   * loop (sky-hail), the negative delay puts every stone mid-flight. */
  const hail = document.getElementById("sky-hail");
  scatter(hail, 28, (el) => {
    const size = rand(9, 13);
    el.className = "hailstone";
    el.style.left = `${rand(0, 99.5)}%`;
    el.style.width = `${size}px`;
    el.style.height = `${size}px`;
    el.style.animationDuration = `${rand(1.5, 2.1)}s`;
    el.style.animationDelay = `${rand(-2.1, 0)}s`;
  });
}
