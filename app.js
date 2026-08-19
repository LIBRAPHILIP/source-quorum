const view = document.getElementById("source-view");
const buttons = document.querySelectorAll(".tabs button");

async function loadSource(path) {
  view.textContent = "Loading " + path + " …";
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error(String(res.status));
    view.textContent = await res.text();
  } catch (err) {
    view.textContent =
      "Could not load " +
      path +
      " from this host.\nOpen it on GitHub: https://github.com/LIBRAPHILIP/source-quorum/blob/main/" +
      path.replace("./", "");
  }
}

buttons.forEach((btn) => {
  btn.addEventListener("click", () => {
    buttons.forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
    loadSource(btn.dataset.src);
  });
});

if (buttons[0]) loadSource(buttons[0].dataset.src);

fetch("./deployed.json")
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null)
  .then((data) => {
    if (!data || !data.address) return;
    const slot = document.getElementById("deploy-slot");
    if (!slot) return;
    slot.textContent =
      "SourceQuorum on " +
      (data.network || "unknown") +
      ": " +
      data.address +
      (data.bond?.address ? " · QuorumBond " + data.bond.address : "");
  });

const links = document.querySelectorAll("nav a[href^='#']");
const sections = [...links]
  .map((a) => document.querySelector(a.getAttribute("href")))
  .filter(Boolean);

const io = new IntersectionObserver(
  (entries) => {
    const visible = entries
      .filter((e) => e.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    links.forEach((a) =>
      a.classList.toggle("active", a.getAttribute("href") === "#" + visible.target.id)
    );
  },
  { rootMargin: "-20% 0px -70% 0px", threshold: [0.1, 0.25] }
);
sections.forEach((s) => io.observe(s));
