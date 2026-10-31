cmake_minimum_required(VERSION 3.28)
project({{project_name}} LANGUAGES CXX)

# Compiler floor, warnings, sanitizers, GoogleTest and the add_project_* helpers.
include(cmake/ProjectSettings.cmake)

# Add targets with the helpers so none can forget the shared options and warnings:
#   add_project_library(<name> STATIC <sources...>)
#   add_project_executable(<name> <sources...>)
#   add_project_test(<name> <sources...>)   # GoogleTest, registered with ctest

add_project_test(smoke_test tests/smoke_test.cpp)
