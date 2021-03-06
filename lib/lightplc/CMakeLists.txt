#
# Gr-plc - IEEE 1901 module for GNU Radio
# Copyright (C) 2016 Roee Bar <roeeb@ece.ubc.ca>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

cmake_minimum_required(VERSION 2.6)
find_package(PythonInterp)

if(NOT CMAKE_BUILD_TYPE)
   set(CMAKE_BUILD_TYPE "Release")
   message(STATUS "Build type not specified: defaulting to release.")
endif(NOT CMAKE_BUILD_TYPE)

# compile with c++11
SET(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -std=c++11")

# lightplc lib
add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/mapping.inc
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/generate_map.py
    COMMAND ${PYTHON_EXECUTABLE} ${PYTHON_DASH_B}
    ${CMAKE_CURRENT_SOURCE_DIR}/generate_map.py > ${CMAKE_CURRENT_BINARY_DIR}/mapping.inc
)

include_directories(
    ${CMAKE_CURRENT_BINARY_DIR}/
    )

list(APPEND generated_sources ${CMAKE_CURRENT_BINARY_DIR}/mapping.inc)
add_custom_target(generated_sources DEPENDS ${generated_sources})

# requires it++ and fftw libraries
list(APPEND lightplc_libs
  itpp
  fftw3f
)

# source files
list(APPEND lightplc_sources
    phy_service.cc
    utils.cc
)

# create a static library
add_library(lightplc STATIC ${lightplc_sources})
add_dependencies(lightplc generated_sources)
target_link_libraries(lightplc ${lightplc_libs})
set_target_properties(lightplc PROPERTIES COMPILE_FLAGS "-fPIC") # static libraries needs -fPIC in x86 arch

# create an executable test
list(APPEND phy_test_sources
    phy_service.cc
    utils.cc
    qa_phy_service.cc
    phy_test.cc
    )
add_executable(phy_test ${phy_test_sources})
target_link_libraries(phy_test itpp fftw3f)
