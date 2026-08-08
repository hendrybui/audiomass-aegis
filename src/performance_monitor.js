// Performance monitoring helper
// Add this to any critical loading functions

(function() {
    'use strict';
    
    // Performance monitoring utilities
    window.AudioMassPerformance = {
        // Monitor and warn about slow operations
        measure: function(operationName, thresholdMs) {
            var start = performance.now();
            return function() {
                var duration = performance.now() - start;
                if (duration > thresholdMs) {
                    console.warn('⚠️ SLOW OPERATION: ' + operationName + ' took ' + duration.toFixed(2) + 'ms');
                } else {
                    console.log('✓ ' + operationName + ': ' + duration.toFixed(2) + 'ms');
                }
                return duration;
            };
        },
        
        // Check for parallel vs sequential loading
        detectSequentialLoading: function(promises) {
            if (!Array.isArray(promises) || promises.length === 0) return false;
            
            var start = performance.now();
            var completed = 0;
            
            promises.forEach(function(p) {
                if (p && p.then) {
                    p.then(function() { completed++; });
                }
            });
            
            // If this check takes longer than expected, might be sequential
            setTimeout(function() {
                var elapsed = performance.now() - start;
                if (completed === 0 && elapsed > 1000) {
                    console.error('❌ ERROR: Possible sequential loading detected!');
                }
            }, 1000);
        },
        
        // Alert on performance violations
        alertOnViolation: function(operation, duration, threshold) {
            if (duration > threshold) {
                var message = '⚠️ PERFORMANCE ALERT: ' + operation + ' exceeded ' + threshold + 'ms (took ' + duration + 'ms)';
                console.error(message);
                // Could show user notification here
            }
        }
    };
    
    console.log('✅ Performance monitoring initialized');
})();
