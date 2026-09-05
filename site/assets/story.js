// Every chapter is a normal page; reading also works without JavaScript.
document.addEventListener('keydown', (event) => {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (event.target.closest('input, textarea, select, button, [contenteditable="true"], [role="dialog"], .figure-scroll')) return;
  if (window.getSelection()?.toString()) return;
  const direction = event.key === 'ArrowRight' ? 'next' : event.key === 'ArrowLeft' ? 'prev' : null;
  if (!direction) return;
  const destination = document.querySelector(`.pager a[rel="${direction}"]`);
  if (destination) {
    event.preventDefault();
    window.location.assign(destination.href);
  }
});
