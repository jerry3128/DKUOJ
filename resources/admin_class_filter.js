;(function() {
    var $jq = window.django && django.jQuery ? django.jQuery : jQuery;
    var $alt = window.jQuery && window.jQuery !== $jq ? window.jQuery : null;

    $jq(document).ready(function() {
        var $orgField = $jq('#id_organizations');
        var $classField = $jq('#id_classes');

        if (!$orgField.length || !$classField.length) return;

        function addOrganizationsParam(options, orgIds) {
            if (!orgIds.length) {
                return;
            }

            var data = options.data;
            var orgsParam = 'organizations=' + encodeURIComponent(orgIds.join(','));

            if (typeof data === 'function') {
                var originalData = data;
                options.data = function(params) {
                    var result = originalData(params) || {};
                    result.organizations = orgIds.join(',');
                    return result;
                };
                return;
            }

            // Handle string data (URL-encoded parameters)
            if (typeof data === 'string') {
                options.data = data + '&' + orgsParam;
                return;
            }

            // Handle object data
            options.data = data || {};
            options.data.organizations = orgIds.join(',');
        }

        function registerPrefilter($instance) {
            if (!$instance || !$instance.ajaxPrefilter) {
                return;
            }

            $instance.ajaxPrefilter(function(options) {
                if (options.url && options.url.indexOf('judge-select2/class') !== -1) {
                    var orgIds = $orgField.val() || [];
                    if (typeof orgIds === 'string') {
                        orgIds = [orgIds];
                    }
                    addOrganizationsParam(options, orgIds);
                }
            });
        }

        registerPrefilter($jq);
        if ($alt) {
            registerPrefilter($alt);
        }
    });
}());
