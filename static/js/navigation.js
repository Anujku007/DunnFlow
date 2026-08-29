document.addEventListener("DOMContentLoaded", () => {

    const navLinks = document.querySelectorAll(".nav-link");

    const sections = [
        {
            id: "control-center",
            link: document.querySelector('.nav-link[href="#control-center"]')
        },
        {
            id: "demo-lab",
            link: document.querySelector('.nav-link[href="#demo-lab"]')
        },
        {
            id: "reports",
            link: document.querySelector('.nav-link[href="#reports"]')
        },
        {
            id: "audit-log",
            link: document.querySelector('.nav-link[href="#audit-log"]')
        }
    ];

    function setActiveLink(activeLink) {
        navLinks.forEach(link => {
            link.classList.remove("active");
        });

        if (activeLink) {
            activeLink.classList.add("active");
        }
    }

    /*
     * Smooth scrolling for navigation links.
     */
    navLinks.forEach(link => {
        link.addEventListener("click", event => {
            const targetId = link.getAttribute("href");

            if (!targetId || !targetId.startsWith("#")) {
                return;
            }

            const target = document.querySelector(targetId);

            if (!target) {
                return;
            }

            event.preventDefault();

            target.scrollIntoView({
                behavior: "smooth",
                block: "start"
            });

            setActiveLink(link);

            history.replaceState(null, "", targetId);
        });
    });

    /*
     * Automatically update the active navigation item
     * while the user scrolls through the dashboard.
     */
    const observer = new IntersectionObserver(
        entries => {

            const visibleSections = entries
                .filter(entry => entry.isIntersecting)
                .sort((a, b) => {
                    return b.intersectionRatio - a.intersectionRatio;
                });

            if (visibleSections.length === 0) {
                return;
            }

            const activeSection = sections.find(
                section => section.id === visibleSections[0].target.id
            );

            if (activeSection) {
                setActiveLink(activeSection.link);
            }
        },
        {
            root: null,
            threshold: [0.2, 0.4, 0.6],
            rootMargin: "-90px 0px -35% 0px"
        }
    );

    sections.forEach(section => {
        const element = document.getElementById(section.id);

        if (element) {
            observer.observe(element);
        }
    });

    /*
     * Restore the correct navigation state when the page
     * is loaded with a hash in the URL.
     */
    const currentHash = window.location.hash;

    if (currentHash) {
        const matchingLink = document.querySelector(
            `.nav-link[href="${currentHash}"]`
        );

        if (matchingLink) {
            setActiveLink(matchingLink);
        }
    }

});