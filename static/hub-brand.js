/* No animation timer or requestAnimationFrame: CSS transforms only. */
(()=>{const update=()=>document.documentElement.classList.toggle('motion-document-hidden',document.hidden);document.addEventListener('visibilitychange',update);update();})();
