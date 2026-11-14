// Applies the stored theme before first paint (no flash); storage may be blocked.
try{var t=localStorage.getItem("pk_theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch{}
