document.addEventListener('DOMContentLoaded', function () {
    const codeInput = document.getElementById('id_code');
    if (!codeInput) return;

    const url = new URL(window.location.href);
    const isOriginalAdvancedPage = url.searchParams.get('advanced') === '1' ||
        document.querySelector('input[name="_advanced_mode"][value="1"]');

    const isAddPage = window.location.pathname.endsWith('/add/');
    if (!isAddPage) return;

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

    async function autofillProblemCode() {
        try {
            const uniqueCode = await generateUniqueCloneCode();
            codeInput.value = uniqueCode;
            codeInput.dispatchEvent(new Event('change', {bubbles: true}));
            return uniqueCode;
        } catch (error) {
            console.error('Failed to generate code:', error);
            return null;
        }
    }

    window.DKUOJAutofillProblemCode = autofillProblemCode;
    if (isOriginalAdvancedPage && codeInput.value.trim() === '') {
        autofillProblemCode();
    }
});
