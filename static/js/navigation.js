/*
 * DunnFlow — Navigation
 *
 * Responsibilities:
 * - Section navigation.
 * - Active navigation state.
 * - Smooth scrolling.
 *
 * IMPORTANT:
 * Navigation does NOT determine recovery mode.
 * Navigation does NOT execute recovery.
 * Navigation does NOT call backend APIs.
 */

(function () {
    "use strict";

    const NAV_SELECTOR = ".nav-link";
    const SECTION_SELECTOR = "section[id]";

    let navLinks = [];
    let sections = [];
    let observer = null;


    /**
     * Set the active navigation item.
     */
    function setActiveNav(sectionId) {
        if (!sectionId) {
            return;
        }

        navLinks.forEach((link) => {
            const target =
                link.getAttribute("href");

            const isActive =
                target === `#${sectionId}`;

            link.classList.toggle(
                "active",
                isActive
            );

            link.setAttribute(
                "aria-current",
                isActive ? "page" : "false"
            );
        });
    }


    /**
     * Scroll to a section.
     */
    function scrollToSection(sectionId) {
        if (!sectionId) {
            return;
        }

        const section =
            document.getElementById(sectionId);

        if (!section) {
            return;
        }

        section.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    }


    /**
     * Handle navigation clicks.
     */
    function handleNavClick(event) {
        const link =
            event.currentTarget;

        const href =
            link.getAttribute("href");

        if (
            !href ||
            !href.startsWith("#") ||
            href.length <= 1
        ) {
            return;
        }

        const sectionId =
            href.substring(1);

        const section =
            document.getElementById(sectionId);

        if (!section) {
            return;
        }

        event.preventDefault();

        setActiveNav(sectionId);

        scrollToSection(sectionId);
    }


    /**
     * Observe visible sections so the navigation
     * highlight follows the user's scroll position.
     *
     * This affects ONLY visual navigation state.
     * It never changes DunnFlowState.mode.
     */
    function createSectionObserver() {
        if (
            typeof IntersectionObserver ===
            "undefined"
        ) {
            return;
        }

        observer =
            new IntersectionObserver(
                (entries) => {
                    const visibleEntries =
                        entries
                            .filter(
                                (entry) =>
                                    entry.isIntersecting
                            )
                            .sort(
                                (a, b) =>
                                    b.intersectionRatio -
                                    a.intersectionRatio
                            );

                    if (
                        visibleEntries.length === 0
                    ) {
                        return;
                    }

                    const sectionId =
                        visibleEntries[0]
                            .target
                            .id;

                    setActiveNav(sectionId);
                },
                {
                    root: null,
                    rootMargin:
                        "-15% 0px -65% 0px",
                    threshold: [
                        0,
                        0.25,
                        0.5,
                        0.75,
                        1
                    ]
                }
            );

        sections.forEach((section) => {
            observer.observe(section);
        });
    }


    /**
     * Initialize navigation.
     */
    function initNavigation() {
        navLinks = Array.from(
            document.querySelectorAll(
                NAV_SELECTOR
            )
        );

        sections = Array.from(
            document.querySelectorAll(
                SECTION_SELECTOR
            )
        );

        navLinks.forEach((link) => {
            link.addEventListener(
                "click",
                handleNavClick
            );
        });

        createSectionObserver();

        /*
         * Control Center is the initial visual section.
         * This does NOT set recovery state.
         */
        const firstSection =
            sections.find(
                (section) =>
                    section.id ===
                    "control-center"
            ) || sections[0];

        if (firstSection) {
            setActiveNav(
                firstSection.id
            );
        }
    }


    /**
     * Public navigation helpers.
     */
    window.DunnFlowNavigation = {
        init: initNavigation,
        setActive: setActiveNav,
        scrollTo: scrollToSection
    };


    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initNavigation,
            { once: true }
        );
    } else {
        initNavigation();
    }
})();