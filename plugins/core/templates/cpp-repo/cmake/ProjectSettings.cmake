# Project-wide build settings: compiler floor, standard, warnings, sanitizers, GoogleTest and the
# add_project_* target helpers. Included once from the top-level CMakeLists.txt, before any target.
#
# Scaffolded by the setup-cpp-repo skill (eudaldrg-workflows); this repo owns the file from here on.
# docs/tasks/testing.md says which checks build which configuration.

# ---------------------------------------------------------------------------- standard and layout

set(CMAKE_CXX_STANDARD {{cxx_standard}})
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
# clang-tidy and cppcheck read build/debug/compile_commands.json.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")

# ---------------------------------------------------------------------------- compiler floor
# The oldest compilers this project supports. Below them the standard library lacks features the
# code relies on, and the failure would otherwise show up as an obscure error deep in a header.

set(PROJECT_GCC_FLOOR "{{gcc_floor}}")
set(PROJECT_CLANG_FLOOR "{{clang_floor}}")
set(PROJECT_MSVC_FLOOR "{{msvc_floor}}")       # Visual Studio version
set(PROJECT_MSVC_FLOOR_VERSION {{msvc_floor_version}})  # the matching MSVC_VERSION

if(MSVC AND NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
  if(MSVC_VERSION LESS PROJECT_MSVC_FLOOR_VERSION)
    message(FATAL_ERROR "MSVC ${MSVC_VERSION} is below this project's floor "
                        "(Visual Studio ${PROJECT_MSVC_FLOOR}, MSVC_VERSION ${PROJECT_MSVC_FLOOR_VERSION})")
  endif()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
  if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS PROJECT_GCC_FLOOR)
    message(FATAL_ERROR "GCC ${CMAKE_CXX_COMPILER_VERSION} is below this project's floor (GCC ${PROJECT_GCC_FLOOR})")
  endif()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
  if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS PROJECT_CLANG_FLOOR)
    message(FATAL_ERROR "Clang ${CMAKE_CXX_COMPILER_VERSION} is below this project's floor (Clang ${PROJECT_CLANG_FLOOR})")
  endif()
else()
  message(WARNING "Compiler ${CMAKE_CXX_COMPILER_ID} is not one this project tests with")
endif()

# ---------------------------------------------------------------------------- options

add_library(project_options INTERFACE)
if(MSVC)
  target_compile_options(project_options INTERFACE
    /permissive-        # standard conformance
    /utf-8              # source and execution charset
    /Zc:__cplusplus     # report the real standard in __cplusplus
    /Zc:preprocessor    # conforming preprocessor
  )
endif()

# ---------------------------------------------------------------------------- warnings
# Warnings are errors. Silence one only at the line that triggers it, with a reason (AGENTS.md).
# Dependencies are fetched as SYSTEM, so none of this fires on third-party headers.

add_library(project_warnings INTERFACE)
if(MSVC)
  target_compile_options(project_warnings INTERFACE
    /W4 /WX
    # /W4 already covers shadowing (C4456-C4459) and most narrowing (C4244, C4267).
    /w14242   # conversion, possible loss of data        (-Wconversion)
    /w14254   # larger bit field assigned to smaller one (-Wconversion)
    /w14365   # signed/unsigned mismatch in conversion   (-Wsign-conversion)
    /w14826   # sign-extending conversion                (-Wsign-conversion)
    /w14263   # member function hides a virtual one      (-Woverloaded-virtual)
    /w14265   # virtual functions, non-virtual destructor (-Wnon-virtual-dtor)
    /w14287   # unsigned/negative constant mismatch
    /we4289   # loop variable used outside the loop
    /w14296   # expression is always true or false
    /w14311   # pointer truncation
    /w14545 /w14546 /w14547 /w14549 /w14555  # expressions with no effect
    /w14640   # thread-unsafe static local initialisation
    /w14905 /w14906  # string literal cast to a different string type
    /w14928   # illegal copy-initialisation
    /external:anglebrackets /external:W0  # no warnings from <system> headers
  )
else()
  target_compile_options(project_warnings INTERFACE
    -Wall -Wextra -Wpedantic -Werror
    -Wshadow
    -Wconversion -Wsign-conversion
    -Wnon-virtual-dtor -Woverloaded-virtual
  )
endif()

# ---------------------------------------------------------------------------- sanitizers
# Applied to every target, dependencies included, not through an interface target: an
# uninstrumented library hides bugs from ASan/TSan, and MSVC refuses to link ASan objects against
# uninstrumented STL users (LNK2038 annotate_vector mismatch). Each sanitizer configuration has its
# own build directory (CMakePresets.json: asan, tsan).

option(ENABLE_ASAN "Enable AddressSanitizer" OFF)
option(ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer" OFF)
option(ENABLE_TSAN "Enable ThreadSanitizer" OFF)

if(ENABLE_TSAN AND ENABLE_ASAN)
  message(FATAL_ERROR "ENABLE_TSAN and ENABLE_ASAN cannot share a binary; use the tsan and asan presets")
endif()

if(MSVC)
  if(ENABLE_TSAN)
    message(FATAL_ERROR "MSVC has no ThreadSanitizer; run the tsan preset on Linux")
  endif()
  if(ENABLE_UBSAN)
    message(WARNING "MSVC has no UndefinedBehaviorSanitizer; ENABLE_UBSAN is ignored")
  endif()
  if(ENABLE_ASAN)
    add_compile_options(/fsanitize=address /Zi)
    add_link_options(/INCREMENTAL:NO)
    # The runtime checks /RTC1 adds to Debug builds are incompatible with ASan.
    string(REGEX REPLACE "/RTC[1csu]+" "" CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG}")
  endif()
else()
  set(_project_sanitize_flags "")
  if(ENABLE_ASAN)
    list(APPEND _project_sanitize_flags -fsanitize=address -fno-omit-frame-pointer)
  endif()
  if(ENABLE_UBSAN)
    # Without -fno-sanitize-recover, UBSan only prints and the test still passes.
    list(APPEND _project_sanitize_flags -fsanitize=undefined -fno-sanitize-recover=undefined)
  endif()
  if(ENABLE_TSAN)
    list(APPEND _project_sanitize_flags -fsanitize=thread)
  endif()
  if(_project_sanitize_flags)
    add_compile_options(${_project_sanitize_flags})
    add_link_options(${_project_sanitize_flags})
  endif()
endif()

# ---------------------------------------------------------------------------- tests

option(BUILD_TESTING "Build test targets" ON)
# Runs every discovered test under a cgroup memory cap (scripts/with_memory_cap.py), so a runaway
# test fails on its own instead of getting the whole session OOM-killed. Linux with a systemd user
# session only; elsewhere the launcher runs the test uncapped.
option(ENABLE_TEST_MEMORY_CAP "Run tests under a memory cap" {{memory_cap_default}})

if(BUILD_TESTING)
  include(FetchContent)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)  # match CMake's default /MD runtime on MSVC
  FetchContent_Declare(
    googletest
    URL https://github.com/google/googletest/archive/refs/tags/{{googletest_tag}}.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM
  )
  FetchContent_MakeAvailable(googletest)
  enable_testing()
  include(GoogleTest)

  if(ENABLE_TEST_MEMORY_CAP)
    if(CMAKE_VERSION VERSION_LESS 3.29)
      message(FATAL_ERROR "ENABLE_TEST_MEMORY_CAP needs CMake 3.29+ (the TEST_LAUNCHER property)")
    endif()
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
  endif()
endif()

# ---------------------------------------------------------------------------- target helpers
# Every target goes through one of these, so none can forget the shared options and warnings.

function(add_project_library name)
  add_library(${name} ${ARGN})
  target_link_libraries(${name} PRIVATE project_options project_warnings)
endfunction()

function(add_project_executable name)
  add_executable(${name} ${ARGN})
  target_link_libraries(${name} PRIVATE project_options project_warnings)
endfunction()

function(add_project_test name)
  if(NOT BUILD_TESTING)
    return()
  endif()
  add_executable(${name} ${ARGN})
  target_link_libraries(${name} PRIVATE project_options project_warnings GTest::gtest_main)
  if(ENABLE_TEST_MEMORY_CAP)
    set_property(TARGET ${name} PROPERTY TEST_LAUNCHER
                 "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/scripts/with_memory_cap.py")
  endif()
  # PRE_TEST: discover when ctest runs, not at build time, so a build never executes a test binary.
  gtest_discover_tests(${name} DISCOVERY_MODE PRE_TEST)
  set_property(GLOBAL APPEND PROPERTY PROJECT_TEST_TARGETS ${name})
endfunction()

# `project_tests` builds every add_project_test() target; scripts/run_sanitizers.py builds only it.
# Deferred to the end of the top-level directory so it sees tests added in any subdirectory.
function(_project_define_tests_target)
  get_property(_targets GLOBAL PROPERTY PROJECT_TEST_TARGETS)
  add_custom_target(project_tests)
  if(_targets)
    add_dependencies(project_tests ${_targets})
  endif()
endfunction()
cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL _project_define_tests_target)
