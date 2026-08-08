# Performance Safeguards - AudioMass

## Critical Performance Rules (Never Break These!)

### 1. PARALLEL LOADING MANDATORY
- ✅ Audio clips MUST load in parallel using `Promise.all()`
- ❌ NEVER load clips sequentially in a for loop
- **Impact:** Sequential loading = 8x slower for 8 clips

### 2. STEM SEPARATION REQUIREMENTS  
- ✅ PyTorch threading MUST use `torch.set_num_threads(1)`
- ❌ NEVER use default PyTorch settings in daemon threads
- **Impact:** Prevents "terminate called without active exception" crashes

### 3. FILE SERVING OPTIMIZATION
- ✅ Use `FileResponse` with proper mime types
- ✅ Check file exists before serving
- ❌ NEVER assume files exist without verification

### 4. PROJECT LOAD OPTIMIZATION
```javascript
// ✅ CORRECT - Parallel loading
var promises = clipIds.map(function(cid) {
    return fetch(url).then(r => r.arrayBuffer());
});
Promise.all(promises).then(function(results) {
    // Process all results at once
});

// ❌ WRONG - Sequential loading  
for (var i = 0; i < clipIds.length; i++) {
    var result = await fetch(url);  // AWAITS EACH ONE!
}
```

### 5. MEMORY MANAGEMENT
- ✅ Close AudioContext after project load
- ✅ Clean up temp buffers
- ❌ NEVER leave AudioContext instances open

## Automated Checks

### Pre-commit Testing
```bash
# Test project loading performance
curl -s http://localhost:5055/api/projects > /dev/null
echo "✓ Project API responding"
```

### Load Testing
```bash
# Test with large project
# Create test project with 10+ clips
# Verify it loads in <5 seconds
```

### Code Review Checklist
- [ ] No sequential audio loading loops
- [ ] All concurrent operations use Promise.all/await
- [ ] PyTorch operations set thread limits
- [ ] File serving has existence checks
- [ ] Memory cleanup after operations

## Performance Budgets

### Maximum Load Times
- Small project (1-3 clips): <2 seconds
- Medium project (4-6 clips): <4 seconds  
- Large project (7-12 clips): <6 seconds
- Stem separation: <30 seconds for 3min song

### File Size Limits
- Single clip: 100MB max
- Total project: 500MB max recommended
- Stem file size: 50MB per stem (41MB actual)

## Warning Signs
🚨 **PROBLEM INDICATORS:**
- Loading progress stuck for >10 seconds
- Progress shows "Loading clips... 1/8" for long time
- Browser shows "Unresponsive" 
- High CPU usage during idle times

## Recovery Procedures
If slow loading returns:
1. Check for sequential for loops
2. Verify Promise.all() usage
3. Test with simple project first
4. Check network tab in browser DevTools
