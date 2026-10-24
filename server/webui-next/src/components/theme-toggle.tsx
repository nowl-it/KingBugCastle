"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

const STORAGE_KEY = "kgc-theme";

/**
 * Light/dark switch. The preference is stored under `kgc-theme` ("light" |
 * "dark"); when unset the system `prefers-color-scheme` decides. The actual
 * class is applied on <html> by an inline script in layout.tsx before
 * hydration to avoid a theme flash, so this component only mirrors and
 * mutates that class.
 */
function subscribe(onChange: () => void) {
	// The class is external state: the pre-hydration script, other toggles,
	// and other tabs (storage event) can all change it.
	const observer = new MutationObserver(onChange);
	observer.observe(document.documentElement, {
		attributes: true,
		attributeFilter: ["class"],
	});
	window.addEventListener("storage", onChange);
	return () => {
		observer.disconnect();
		window.removeEventListener("storage", onChange);
	};
}

function getSnapshot() {
	return document.documentElement.classList.contains("dark");
}

function getServerSnapshot() {
	return false;
}

export function ThemeToggle() {
	const dark = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

	const toggle = () => {
		const next = !dark;
		document.documentElement.classList.toggle("dark", next);
		try {
			localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
		} catch {
			// Private browsing with storage disabled: the theme still applies
			// for this session, just won't persist.
		}
	};

	return (
		<button
			type="button"
			onClick={toggle}
			aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
			title={dark ? "Switch to light mode" : "Switch to dark mode"}
			className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
		>
			{dark ? <Sun size={16} /> : <Moon size={16} />}
		</button>
	);
}
