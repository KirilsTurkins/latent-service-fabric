document.querySelector('#check').addEventListener('click', async () => {
  const result = document.querySelector('#result');
  result.textContent = 'Checking…';
  try {
    const response = await fetch('/api/status', {credentials: 'omit', cache: 'no-store'});
    const value = await response.json();
    result.textContent = response.ok ? `Service is ${value.status}.` : 'Service is unavailable. Try again later.';
  } catch {
    result.textContent = 'The request could not finish.';
  }
});
