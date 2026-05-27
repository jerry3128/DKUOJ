document.addEventListener('DOMContentLoaded', function () {
    const codeInput = document.getElementById('id_code');
    if (!codeInput) return;

    // 只在 add 页面并且当前 code 为空时自动填充
    const isAddPage = window.location.pathname.endsWith('/add/');
    if (!isAddPage) return;
    if (codeInput.value.trim() !== '') return;

    async function checkProblemCode(code) {
        if (!code || code.trim() === '') {
            return null;
        }

        try {
            const response = await fetch(`/api/v2/problem/check-code/?code=${encodeURIComponent(code)}`, {
                method: 'GET',
                cache: 'no-cache',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                return null;
            }

            const data = await response.json();
            return data.exists;
        } catch (error) {
            console.error('Checking Failed:', error);
            return null;
        }
    }

    async function generateUniqueCloneCode() {
        const max = 1000000;

        for (let i = 0; i < max; i++) {
            const code = `p${i.toString().padStart(6, '0')}`;
            const exists = await checkProblemCode(code);

            if (exists === false) {
                return code;
            }
        }

        const timestamp = Date.now().toString().slice(-6);
        return `clone${timestamp}`;
    }

    async function initialize() {
        try {
            const uniqueCode = await generateUniqueCloneCode();
            codeInput.value = uniqueCode;
        } catch (error) {
            console.error('Failed to generate code:', error);
        }
    }

    initialize();
});