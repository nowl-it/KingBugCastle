/* Applied before first paint (synchronous script in <head>) so the stored or
   system theme is on <html> before any token-based CSS renders. Kept as a
   plain file to avoid an inline dangerouslySetInnerHTML script.
   Next's static export copies public/ into out/, and dashboard.py's
   non-API catch-all serves it directly. */
(function () {
	var stored = null;
	var dark = false;
	try {
		stored = localStorage.getItem("kgc-theme");
		dark = stored
			? stored === "dark"
			: window.matchMedia("(prefers-color-scheme: dark)").matches;
		document.documentElement.classList.toggle("dark", !!dark);
	} catch (e) {
		/* Storage or matchMedia unavailable: stay light. */
	}
})();
