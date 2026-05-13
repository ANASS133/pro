(function () {
    var clientPromise = null;

    function readConfig() {
        var config = window.SUPABASE_CONFIG || {};
        var url = String(config.url || window.SUPABASE_URL || "").trim();
        var anonKey = String(config.anonKey || window.SUPABASE_ANON_KEY || "").trim();

        if (!url || !anonKey) {
            throw new Error("Supabase environment variables are missing.");
        }

        return { url: url, anonKey: anonKey };
    }

    async function getClient() {
        if (clientPromise) {
            return clientPromise;
        }

        clientPromise = import("https://esm.sh/@supabase/supabase-js@2.105.4")
            .then(function (module) {
                var config = readConfig();
                return module.createClient(config.url, config.anonKey, {
                    auth: {
                        persistSession: false,
                        autoRefreshToken: false,
                        detectSessionInUrl: false,
                    },
                });
            });

        return clientPromise;
    }

    window.AppSupabase = {
        getClient: getClient,
        readConfig: readConfig,
    };
})();
