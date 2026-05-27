document.addEventListener('DOMContentLoaded', function () {
    const keyInput = document.getElementById('id_key');
    if (!keyInput) return;

    // 只在 add 页面并且 key 为空时自动填充
    const isAddPage = window.location.pathname.endsWith('/add/');
    if (!isAddPage) return;
    if (keyInput.value.trim() !== '') return;

    async function checkContestKey(key) {
        if (!key || key.trim() === '') return null;

        try {
            const response = await fetch(`/api/v2/contest/check-key/?key=${encodeURIComponent(key)}`, {
                method: 'GET',
                cache: 'no-cache',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) return null;

            const data = await response.json();
            return data.exists;
        } catch (e) {
            console.error(e);
            return null;
        }
    }

    async function generateUniqueContestKey() {
        const max = 1000000;

        for (let i = 0; i < max; i++) {
            const key = `c${i.toString().padStart(6, '0')}`;
            const exists = await checkContestKey(key);

            if (exists === false) return key;
            if (exists === null) throw new Error('check failed');
        }

        const timestamp = Date.now().toString().slice(-6);
        return `contest${timestamp}`;
    }

    async function init() {
        try {
            const key = await generateUniqueContestKey();
            keyInput.value = key;
        } catch (e) {
            console.error('Failed to generate contest key:', e);
        }
    }

    init();
});