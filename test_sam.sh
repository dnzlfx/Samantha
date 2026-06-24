#!/bin/bash
# Samantha v1.0 - Test Suite
# Tests all major features

echo "================================"
echo "Samantha v1.0 - COMPREHENSIVE TESTS"
echo "================================"
echo ""

# Test 1: Basic startup and response
echo "TEST 1: Basic startup and conversation"
echo "---------------------------------------"
printf "n\n1\nHola Sam\nsalir\n" | timeout 20 python sam.py 2>&1 | grep -A 2 "Sam:"
if [ $? -eq 0 ]; then
    echo "✅ PASS: Basic conversation works"
else
    echo "❌ FAIL: Basic conversation"
fi
echo ""

# Test 2: Auto-search detection  
echo "TEST 2: Auto-search keyword detection"
echo "---------------------------------------"
printf "n\n1\nque paso ayer en venezuela\nsalir\n" | timeout 25 python sam.py 2>&1 | grep "Detectada necesidad de busqueda"
if [ $? -eq 0 ]; then
    echo "✅ PASS: Auto-search detection works"
else
    echo "❌ FAIL: Auto-search detection"
fi
echo ""

# Test 3: Auto-switch mode
echo "TEST 3: Auto-switch model mode"
echo "---------------------------------------"
printf "s\ncrea una funcion fibonacci\nsalir\n" | timeout 25 python sam.py 2>&1 | grep -E "(auto-switch|Auto-switch)"
if [ $? -eq 0 ]; then
    echo "✅ PASS: Auto-switch mode activates"
else
    echo "❌ FAIL: Auto-switch mode"
fi
echo ""

# Test 4: Syntax check
echo "TEST 4: Python syntax validation"
echo "---------------------------------------"
python -m py_compile sam.py 2>&1
if [ $? -eq 0 ]; then
    echo "✅ PASS: No syntax errors"
else
    echo "❌ FAIL: Syntax errors found"
fi
echo ""

# Test 5: Module imports
echo "TEST 5: Module imports"
echo "---------------------------------------"
python -c "from core.llm_manager import ModelManager; from core.search_engine import SearchEngine; from core.sandbox import SandboxExecutor; from core.memory import MemoryManager; print('All imports OK')" 2>&1
if [ $? -eq 0 ]; then
    echo "✅ PASS: All core modules import correctly"
else
    echo "❌ FAIL: Module import errors"
fi
echo ""

echo "================================"
echo "TEST SUITE COMPLETE"
echo "================================"
